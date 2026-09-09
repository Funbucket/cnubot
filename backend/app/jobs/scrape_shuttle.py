import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.scrapers.shuttle import scrape_shuttle_schedule


def main() -> None:
    data = scrape_shuttle_schedule()
    data["fetched_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    path = Path("app/static/data/shuttle_schedule.json")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved shuttle schedule: {path}")


if __name__ == "__main__":
    main()
