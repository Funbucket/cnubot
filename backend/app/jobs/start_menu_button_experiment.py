"""Start the independent menu entry test once; never restart an existing test."""
import asyncio

from app.database import connect_database, close_database, get_pool
from app.services.menu_button_experiment import KEY


async def main():
    await connect_database()
    try:
        existing = await get_pool().fetchrow(
            "SELECT id,status FROM experiments WHERE experiment_key=$1", KEY)
        if existing:
            print({"experiment_key": KEY, "status": existing["status"], "created": False})
            return
        raise RuntimeError(
            "자동 시작용 1%/3534명 가정은 폐기했습니다. "
            "cnubot-experiment-review 스킬로 데이터와 계획을 검토한 후 새 실험을 생성하세요.")
    finally:
        await close_database()


if __name__ == "__main__":
    asyncio.run(main())
