import argparse
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.scrapers.academic_calendar import scrape_academic_calendar


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int, default=datetime.now(ZoneInfo("Asia/Seoul")).year)
    parser.add_argument("--output", default="app/static/data/academic_calendar.json")
    args = parser.parse_args()
    data = scrape_academic_calendar(args.year)
    data["fetched_at"] = datetime.now(ZoneInfo("Asia/Seoul")).isoformat()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"saved academic calendar {args.year}: {path}")


if __name__ == "__main__":
    main()
