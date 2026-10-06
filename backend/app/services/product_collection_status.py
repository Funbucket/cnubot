"""Read-only administrator summary; never contacts Toss or exposes raw state."""
import os
from datetime import datetime, timedelta

from app.jobs.collect_products import BUDGET, STATE, slot
from app.services import product_snapshot as store, promotion_settings, recommendation_policy, recommendations


def summary(now=None):
    now = now or datetime.now(store.KST)
    state, snapshot = store.read(STATE), store.read()
    today = state.get("day") == str(now.date())
    blocked = today and bool(state.get("blocked"))
    schedule = [now.replace(hour=h, minute=5, second=0, microsecond=0) for h in (0, 6, 12, 18)]
    due = next((t for t in reversed(schedule) if t <= now), None)
    pending = bool(not blocked and due and (not today or state.get("slot") != slot(now)))
    next_run = (now + timedelta(days=1)).replace(hour=0, minute=5, second=0, microsecond=0)
    if not blocked:
        next_run = due if pending else next((t for t in schedule if t > now), next_run)
    tree = {}

    def walk(nodes, parent=()):
        for node in nodes:
            path = [*parent, node.get("displayName", "")]
            if node.get("categoryId") is not None:
                tree[int(node["categoryId"])] = path
            walk(node.get("children", []), path)

    walk(snapshot.get("categories", {}).get("success", {}).get("categories", []))
    publisher = os.environ.get("TOSS_PUBLISHER_ID", "")
    deal_ids = set(map(str, snapshot.get("lists", {}).get("/openapi/products/today-deals", [])))
    counts = dict.fromkeys(("food", "living", "today_deals"), 0)
    for key, item in snapshot.get("items", {}).items():
        if not item.get("displayPrice") or not item.get("thumbnailUrl") or not snapshot.get("links", {}).get(key + ":" + publisher):
            continue
        if key in deal_ids and store.available(item, snapshot, today=True):
            counts["today_deals"] += 1
        if not store.available(item, snapshot):
            continue
        for cid in ("food", "living"):
            classified = recommendation_policy.classify(item, tree, cid)
            if classified and not recommendations._is_student_excluded(dict(
                    item, _category_names=[name for p in classified["category_paths"] for name in p])):
                counts[cid] += 1
    from app.services.discount_fallback import candidates
    discount_count = len(candidates(snapshot))
    collections = []
    for cid, label in (("today_deals", "오늘 특가"), ("food", "자취생 먹을거"), ("living", "자취생 꿀템")):
        configured = promotion_settings.read_collection(cid) if cid != "today_deals" else None
        fallback_count = sum(p.enabled for p in configured.products) if configured else 0
        mode = configured.mode if configured else "algorithm"
        serving = ("fixed" if mode == "fixed" else "snapshot" if counts[cid]
                   else "discount_fallback" if cid == "today_deals" and discount_count
                   else "fallback" if fallback_count else "empty")
        collections.append({"id": cid, "label": label, "mode": mode, "serving": serving,
                            "available_count": counts[cid], "configured_count": fallback_count,
                            "discount_fallback_count": discount_count if cid == "today_deals" else 0})
    return {"checked_at": now.isoformat(), "status": state.get("status", "not_started"),
            "last_attempt_at": state.get("started_at"), "last_success_at": snapshot.get("updated_at"),
            "next_run_at": next_run.isoformat(), "pending": pending, "blocked_today": blocked,
            "reserved_today": state.get("reserved_products", 0) if today else 0,
            "local_daily_budget": BUDGET, "stored_count": len(snapshot.get("items", {})),
            "collections": collections}
