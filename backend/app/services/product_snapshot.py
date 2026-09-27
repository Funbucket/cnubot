"""Durable product snapshot shared by the collector and request workers."""
import json
import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def directory():
    return Path(os.environ.get("MENU_DATA_DIR", "/data/menus"))


def read(name="product_snapshot.json"):
    try:
        return json.loads((directory() / name).read_text())
    except (FileNotFoundError, ValueError):
        return {}


def write(data, name="product_snapshot.json"):
    directory().mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=directory(), prefix=".products-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, directory() / name)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def available(item, snapshot, today=False):
    now = datetime.now(KST)
    if item.get("isSoldOut"):
        return False
    try:
        updated = datetime.fromisoformat(snapshot["updated_at"])
        if now - updated > timedelta(hours=48):
            return False
        if today and updated.date() != now.date():
            return False
        end = item.get("endAt") or item.get("_deal_end_at")
        if end and datetime.fromisoformat(end) <= now:
            return False
    except (KeyError, ValueError, TypeError):
        return False
    return True


def response(path, params=None):
    """Serve the existing API adapter without making an external request."""
    params = params or {}
    snapshot = read()
    if path == "/openapi/categories":
        return snapshot.get("categories", {"success": {"categories": []}})
    if path == "/openapi/products/detail":
        item = snapshot.get("items", {}).get(str(params.get("tacaItemIds")))
        items = [item] if item and available(item, snapshot) else []
    else:
        ids = snapshot.get("lists", {}).get(path, [])
        items = [snapshot["items"][str(i)] for i in ids if str(i) in snapshot.get("items", {})]
        items = [i for i in items if available(i, snapshot, path.endswith("today-deals"))]
        items = items[:int(params.get("size", 100))]
    return {"success": {"items": items}}
