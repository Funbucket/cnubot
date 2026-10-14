"""Shared public-notice storage and time conventions."""
import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
SEED_PATH = Path(__file__).resolve().parents[1] / "static/data/benefits.json"


def data_path() -> Path:
    return Path(os.environ.get("BENEFITS_DATA_PATH", str(SEED_PATH)))


def read_snapshot(path: Path | None = None) -> dict:
    target = path or data_path()
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        if path is None and target != SEED_PATH:
            return read_snapshot(SEED_PATH)
        return {}
    # Legacy snapshots have fabricated deadlines and no publication dates.
    valid = (isinstance(payload, dict) and payload.get("schema_version") == 2
             and isinstance(payload.get("items"), list) and isinstance(payload.get("sources", {}), dict))
    if valid:
        return payload
    if path is None and target != SEED_PATH:
        return read_snapshot(SEED_PATH)
    return {}
