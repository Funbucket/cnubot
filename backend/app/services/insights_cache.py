"""Bounded per-process analytics cache with shared work for concurrent readers."""
import asyncio
import os
import time
from collections import OrderedDict

_values = OrderedDict()
_pending = {}
TTL = 120
LIMIT = 48


def exclusion_key():
    return (os.getenv('DEVELOPER_ID', ''), os.getenv('EXPERIMENT_QA_IDS', ''))


async def cached(key, loader, *, refresh=False):
    key = (asyncio.get_running_loop(), exclusion_key(), *key)
    now = time.monotonic()
    if refresh:
        _values.pop(key, None)
    found = _values.get(key)
    if found and now - found[0] < TTL:
        _values.move_to_end(key)
        return found[1]
    if key not in _pending:
        async def build():
            try:
                value = await loader()
                _values[key] = (time.monotonic(), value)
                _values.move_to_end(key)
                while len(_values) > LIMIT:
                    _values.popitem(last=False)
                return value
            finally:
                _pending.pop(key, None)
        _pending[key] = asyncio.create_task(build())
    return await asyncio.shield(_pending[key])
