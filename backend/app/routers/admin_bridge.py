"""Encrypted, authenticated transport for administrator JSON APIs.

The reporting key alone never grants administrative permissions. Every request
also needs the original administrator credentials, carried inside the ciphertext.
Only the routes listed here can be dispatched; this is not a general HTTP proxy.
"""
import asyncio
import base64
import json
import logging
import os
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Literal
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.routers.admin import require_admin
from app.routers.insights_api import Envelope, PRIVATE, decode, relay_key

router = APIRouter()
logger = logging.getLogger(__name__)
MAX_BODY = 512_000
MAX_RESPONSE = 6_000_000
ROUTES = {
    'GET': [
        r'/admin/promotion-settings(/collection-status|/diagnostic)?',
        r'/admin/restaurants/catalog',
        r'/admin/api/(experiments|button-experiments)',
        r'/admin/api/button-experiments/[1-9][0-9]*',
        r'/admin/api/experiments/[1-9][0-9]*/(results|diagnostics)',
    ],
    'POST': [
        r'/admin/promotion-settings/(parse|preview)',
        r'/admin/restaurants/(search|preview)',
        r'/admin/api/experiments',
        r'/admin/api/experiments/[1-9][0-9]*/(enrollment|stop|analysis-runs|simulation|preview|preview-override|decision)',
        r'/admin/api/button-experiments/[1-9][0-9]*/(running|paused|completed)',
    ],
    'PUT': [r'/admin/promotion-settings', r'/admin/restaurants/catalog', r'/admin/api/experiments/[1-9][0-9]*'],
    'DELETE': [r'/admin/api/experiments/[1-9][0-9]*/preview-override'],
}
EDITOR_HEADERS = {'x-promotion-editor', 'x-experiment-admin', 'x-restaurants-editor'}


def allowed(method, path):
    return any(re.fullmatch(pattern, path) for pattern in ROUTES.get(method, []))


class AdminMessage(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issued_at: StrictInt
    method: Literal['GET', 'POST', 'PUT', 'DELETE']
    path: str = Field(max_length=180)
    query: str = Field(default='', max_length=4096)
    body: str = Field(default='', max_length=350_000)
    username: str = Field(min_length=1, max_length=1024)
    password: str = Field(min_length=1, max_length=4096)
    headers: dict[str, str] = Field(default_factory=dict)


def aad(direction, request_id):
    return f'admin-bridge:v1:{direction}:{request_id}'.encode()


def unpack(body, key):
    envelope = Envelope.model_validate_json(body)
    if envelope.version != 1 or str(UUID(envelope.id)) != envelope.id:
        raise ValueError('Invalid envelope')
    nonce = decode(envelope.iv, 16)
    if len(nonce) != 12:
        raise ValueError('Invalid nonce')
    plaintext = AESGCM(key).decrypt(nonce, decode(envelope.data, MAX_BODY), aad('request', envelope.id))
    message = AdminMessage.model_validate_json(plaintext)
    if not -30 <= time.time() - message.issued_at <= 90:
        raise ValueError('Expired request')
    if not allowed(message.method, message.path) or any(c in message.query for c in '\r\n#'):
        raise ValueError('Unsupported destination')
    if set(message.headers) - EDITOR_HEADERS or any(v != '1' for v in message.headers.values()):
        raise ValueError('Unsupported header')
    if message.method == 'GET' and message.body:
        raise ValueError('GET body is not supported')
    return envelope.id, message


def pack(request_id, payload, key):
    nonce = secrets.token_bytes(12)
    data = AESGCM(key).encrypt(nonce, json.dumps(payload, ensure_ascii=False).encode(), aad('response', request_id))
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return dict(version=1, id=request_id, iv=encode(nonce), data=encode(data))


def claim_write(request_id):
    # SQLite's primary key arbitrates concurrent workers and survives restarts.
    # A failed/uncertain write is never retried automatically by the transport.
    path = Path(os.getenv('MENU_DATA_DIR', 'data')) / '.admin-bridge-receipts.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(fd)
    with sqlite3.connect(path, timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, created_at REAL NOT NULL)')
        db.execute('DELETE FROM receipts WHERE created_at < ?', (time.time() - 300,))
        try:
            db.execute('INSERT INTO receipts VALUES (?, ?)', (request_id, time.time()))
        except sqlite3.IntegrityError:
            return False
    return True


async def dispatch(app, message):
    credentials = base64.b64encode(f'{message.username}:{message.password}'.encode()).decode()
    body = message.body.encode()
    headers = [(b'host', b'admin-bridge.internal'), (b'authorization', f'Basic {credentials}'.encode()),
               (b'content-type', b'application/json'), (b'content-length', str(len(body)).encode())]
    headers += [(k.encode(), v.encode()) for k, v in message.headers.items()]
    scope = dict(type='http', asgi={'version': '3.0', 'spec_version': '2.3'}, http_version='1.1',
                 method=message.method, scheme='http', path=message.path, raw_path=message.path.encode(),
                 query_string=message.query.encode(), root_path='', headers=headers,
                 server=('admin-bridge.internal', 80), client=('127.0.0.1', 0))
    sent = False
    complete = asyncio.Event()
    status, content_type, chunks, size = 503, 'application/json', [], 0

    async def receive():
        nonlocal sent
        if sent:
            await complete.wait()
            return {'type': 'http.disconnect'}
        sent = True
        return {'type': 'http.request', 'body': body, 'more_body': False}

    async def send(event):
        nonlocal status, content_type, size
        if event['type'] == 'http.response.start':
            status = event['status']
            content_type = dict(event.get('headers', [])).get(b'content-type', b'application/json').decode()
        elif event['type'] == 'http.response.body':
            chunk = event.get('body', b'')
            size += len(chunk)
            if size > MAX_RESPONSE:
                raise ValueError('Response exceeds transport limit')
            chunks.append(chunk)
            if not event.get('more_body', False):
                complete.set()

    await app(scope, receive, send)
    if status >= 500:
        return dict(status=503, content_type='application/json', body=json.dumps({'detail': '관리 기능을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'}))
    if not 200 <= status < 300 and not 400 <= status < 500:
        raise ValueError('Unsupported response status')
    return dict(status=status, content_type=content_type, body=b''.join(chunks).decode())


@router.post('/workspace/relay', include_in_schema=False)
async def bridge(request: Request):
    key = relay_key()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            return JSONResponse({'detail': '요청이 너무 큽니다.'}, status_code=413, headers=PRIVATE)
    try:
        request_id, message = unpack(bytes(body), key)
    except Exception:
        return JSONResponse({'detail': '유효하지 않은 요청입니다.'}, status_code=403, headers=PRIVATE)
    try:
        require_admin(HTTPBasicCredentials(username=message.username, password=message.password))
    except HTTPException:
        payload = dict(status=401, content_type='application/json', body=json.dumps({'detail': '관리자 인증을 확인해 주세요.'}))
        return JSONResponse(pack(request_id, payload, key), headers=PRIVATE)
    try:
        if message.method != 'GET' and not await asyncio.to_thread(claim_write, request_id):
            payload = dict(status=409, content_type='application/json', body=json.dumps({'detail': '이미 처리된 요청입니다. 현황을 새로고침해 주세요.'}))
        else:
            payload = await dispatch(request.app, message)
    except Exception:
        logger.warning('Administrator bridge request unavailable')
        payload = dict(status=503, content_type='application/json', body=json.dumps({'detail': '관리 기능을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'}))
    return JSONResponse(pack(request_id, payload, key), headers=PRIVATE)
