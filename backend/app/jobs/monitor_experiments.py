"""Refresh protocol snapshots every 15 minutes without inventing collection completeness."""
import asyncio
import logging
from datetime import datetime, timezone

from app.database import connect_database, close_database
from app.schemas.experiment_lab import AnalysisInput
from app.services import experiment_lab

logger = logging.getLogger(__name__)


async def refresh():
    designs = await experiment_lab.list_designs()
    now = datetime.now(timezone.utc)
    bucket = int(now.timestamp()) // 900
    for d in designs:
        if d['status'] not in experiment_lab.ACTIVE:
            continue
        try:
            await experiment_lab.run_analysis(d['id'],AnalysisInput(
                idempotency_key=f'monitor-{bucket}',watermark=now,data_complete=False,
                reason='15분 운영 집계 · 수집 완전성 최종 확인은 별도'), 'system')
        except Exception:
            logger.exception('Experiment snapshot refresh failed')


async def main():
    await connect_database()
    try:
        while True:
            await refresh()
            await asyncio.sleep(900)
    finally:
        await close_database()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
