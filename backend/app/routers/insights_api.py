"""Authenticated JSON and a purpose-specific, encrypted reporting transport."""
import base64
import json
import logging
import os
import re
import secrets
import time
from datetime import date
from pathlib import Path
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, StrictInt, ValidationError

from app.routers.admin import require_admin
from app.services.insights_data import ReportName, ReportQuery, load_report

router = APIRouter()
PRIVATE = {'Cache-Control': 'private, no-store', 'Vary': 'Authorization'}
logger = logging.getLogger(__name__)


@router.get('/insights/api/{report}', dependencies=[Depends(require_admin)])
async def report_json(report: ReportName, start_date: date | None = None,
                      end_date: date | None = None, all_time: bool = False, refresh: bool = False):
    try:
        query = ReportQuery(report=report, start_date=start_date, end_date=end_date,
                            all_time=all_time, refresh=refresh)
    except ValidationError:
        return JSONResponse({'error': '조회 기간을 확인해 주세요.'}, status_code=400, headers=PRIVATE)
    try:
        return JSONResponse(jsonable_encoder(await load_report(query)), headers=PRIVATE)
    except Exception:
        logger.warning('Insights JSON report unavailable')
        return JSONResponse({'error': '보고서를 조회하지 못했습니다.'}, status_code=503, headers=PRIVATE)


class Envelope(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: StrictInt
    id: str
    iv: str
    data: str


class Message(BaseModel):
    model_config = ConfigDict(extra='forbid')
    issued_at: StrictInt
    query: ReportQuery


def relay_key():
    value = os.getenv('INSIGHTS_RELAY_KEY', '')
    if not value:
        # Allows adding the dashboard without replacing a container's unrelated
        # runtime settings. This file belongs to the private, persistent data mount.
        path = Path(os.getenv('MENU_DATA_DIR', 'data')) / '.insights-relay-key'
        if path.is_file():
            value = path.read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9_-]{43}=', value):
        raise HTTPException(503, '인사이트 연결 설정이 필요합니다.', headers=PRIVATE)
    return base64.urlsafe_b64decode(value)


def decode(value, limit):
    if len(value) > limit or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise ValueError('Invalid envelope')
    return base64.urlsafe_b64decode(value + '=' * (-len(value) % 4))


def aad(direction, request_id):
    return f'insights-relay:v1:{direction}:{request_id}'.encode()


def unpack(body, key):
    envelope = Envelope.model_validate_json(body)
    if envelope.version != 1 or str(UUID(envelope.id)) != envelope.id:
        raise ValueError('Invalid envelope')
    nonce = decode(envelope.iv, 16)
    if len(nonce) != 12:
        raise ValueError('Invalid envelope')
    plaintext = AESGCM(key).decrypt(nonce, decode(envelope.data, 6000), aad('request', envelope.id))
    message = Message.model_validate_json(plaintext)
    if not -30 <= time.time() - message.issued_at <= 90:
        raise ValueError('Expired request')
    return envelope.id, message.query


def pack(request_id, payload, key):
    nonce = secrets.token_bytes(12)
    body = json.dumps(jsonable_encoder(payload), ensure_ascii=False, separators=(',', ':')).encode()
    data = AESGCM(key).encrypt(nonce, body, aad('response', request_id))
    encode = lambda value: base64.urlsafe_b64encode(value).decode().rstrip('=')
    return {'version': 1, 'id': request_id, 'iv': encode(nonce), 'data': encode(data)}


@router.post('/insights/relay', include_in_schema=False)
async def relay(request: Request):
    # Possession of the dedicated AEAD key authenticates this read-only endpoint.
    # Admin credentials and report contents never traverse the legacy HTTP origin.
    key = relay_key()
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > 8192:
            return JSONResponse({'error': '요청이 너무 큽니다.'}, status_code=413, headers=PRIVATE)
    try:
        request_id, query = unpack(bytes(body), key)
    except Exception:
        return JSONResponse({'error': '유효하지 않은 요청입니다.'}, status_code=403, headers=PRIVATE)
    try:
        payload = {'status': 200, 'body': await load_report(query)}
    except Exception:
        logger.warning('Insights report unavailable')
        payload = {'status': 503, 'body': {'error': '보고서를 조회하지 못했습니다. 잠시 후 다시 시도해 주세요.'}}
    return JSONResponse(pack(request_id, payload, key), headers=PRIVATE)
