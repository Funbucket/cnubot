"""Atomic JSON file replacement preserving existing permissions and ownership."""
import json
import os
import shutil
import tempfile
from pathlib import Path


def write_json_atomic(data: dict, data_dir: Path, filename: str) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = data_dir / filename
    current_stat = path.stat() if path.exists() else None
    payload = json.dumps(data, ensure_ascii=False, indent=4)

    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=data_dir,
        prefix=f".{path.stem}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp_path = Path(tmp.name)

    try:
        json.loads(tmp_path.read_text(encoding="utf-8"))
        if current_stat:
            shutil.copystat(path, tmp_path)
            try:
                os.chown(tmp_path, current_stat.st_uid, current_stat.st_gid)
            except PermissionError:
                pass
        os.replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    return path
