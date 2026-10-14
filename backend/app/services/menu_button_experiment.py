"""Independent assignment for the lunch menu's shopping entry button."""
import logging

from app.database import get_pool
from app.services import experiments, experiment_lab

KEY = "menu_entry_food_vs_today_v1"
BUTTON_ID = "toss_promotion_menu_button"
VARIANTS = {
    "control": {"label": "🍱 자취생 먹을거", "messageText": "자취생 먹을거 핫딜", "collection_id": "food"},
    "treatment": {"label": "🔥 오늘의 핫딜", "messageText": "오늘 특가", "collection_id": "today_deals"},
}
logger = logging.getLogger(__name__)


def create_button(variant_key="treatment"):
    policy = VARIANTS[variant_key]
    return {"label": policy["label"], "action": "message", "messageText": policy["messageText"],
            "extra": {"source": "menu_button", "button_id": BUTTON_ID,
                      "button_label": policy["label"], "collection_id": policy["collection_id"]}}


async def apply(user_id, response):
    if experiment_lab.is_qa(user_id):
        return
    # Assign only when the entry button survived inline-card placement.
    for output in response["template"]["outputs"]:
        for card in output.get("carousel", {}).get("items", []):
            for button in card.get("buttons", []):
                if button.get("extra", {}).get("button_id") != BUTTON_ID:
                    continue
                try:
                    variant = await experiments.get_active_variant(KEY, user_id)
                    if not variant or variant["variant_key"] not in VARIANTS:
                        return
                    policy = VARIANTS[variant["variant_key"]]
                    button.update(label=policy["label"], messageText=policy["messageText"])
                    button["extra"].update(button_label=policy["label"], collection_id=policy["collection_id"])
                    await experiments.record_event(
                        KEY, user_id, "menu_button_exposure", source="menu_button",
                        properties={**policy, "button_id": BUTTON_ID},
                    )
                except Exception:
                    logger.exception("failed to apply menu button experiment")
                return


async def record_click(user_id, entry, collection_id):
    if (experiment_lab.is_qa(user_id) or entry.get("source") != "menu_button"
            or entry.get("button_id") != BUTTON_ID):
        return
    try:
        # Never enroll on click or infer missing Kakao extra. Require a matching
        # prior rendered exposure and the server's actual collection route.
        eligible = await get_pool().fetchval("""
            SELECT EXISTS (
                SELECT 1 FROM user_events u JOIN experiments e ON e.id=u.experiment_id
                JOIN experiment_assignments a ON a.experiment_id=e.id AND a.user_id=u.user_id
                WHERE e.experiment_key=$1 AND e.status='running' AND u.user_id=$2
                  AND u.variant_key=a.variant_key AND u.event_name='menu_button_exposure'
                  AND u.properties->>'label'=$3 AND u.properties->>'collection_id'=$4
            )""", KEY, user_id, entry.get("button_label"), collection_id)
        if eligible:
            await experiments.record_event(
                KEY, user_id, "menu_button_click", source="menu_button",
                properties={"button_id": BUTTON_ID, "label": entry["button_label"], "collection_id": collection_id},
            )
    except Exception:
        logger.exception("failed to record menu button experiment click")
