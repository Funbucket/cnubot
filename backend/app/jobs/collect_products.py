"""Collect at 00:05, 06:05, 12:05, 18:05 KST; serve saved data between runs."""
import argparse
import fcntl
import logging
import time
from datetime import datetime

from app.services import product_snapshot as store, toss_sharelink as api
from app.services.recommendation_policy import classify, supplement_categories

log = logging.getLogger(__name__)
STATE = "product_collection_state.json"
BUDGET = 6000  # Conservatively reserve returned-product capacity before each call.


def slot(now):
    hour = ((now.hour * 60 + now.minute - 5) // 360) * 6
    return f"{now.date()}:{hour}" if hour >= 0 else None


def collect():
    store.directory().mkdir(parents=True, exist_ok=True)
    with (store.directory() / "product_collection.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "already_running"
        now = datetime.now(store.KST)
        current_slot = slot(now)
        state = store.read(STATE)
        if state.get("day") != str(now.date()):
            state = {"day": str(now.date()), "reserved_products": 0}
        if not current_slot or state.get("slot") == current_slot or state.get("blocked"):
            return "not_due"
        # Persist before network access, so restarts cannot repeat a costly run.
        state.update(slot=current_slot, status="running", started_at=now.isoformat())
        store.write(state, STATE)

        def get(path, size=0):
            if state["reserved_products"] + size > BUDGET:
                raise api.TossSharelinkError("LOCAL_DAILY_BUDGET_EXCEEDED")
            state["reserved_products"] += size
            store.write(state, STATE)
            time.sleep(.12)
            return api._get_live_sync(path, {"size": size} if size else None)

        try:
            categories = get("/openapi/categories")
            tree = {}

            def walk(nodes, parent=()):
                for node in nodes:
                    path = [*parent, node["displayName"]]
                    tree[int(node["categoryId"])] = path
                    walk(node.get("children", []), path)

            walk(categories.get("success", {}).get("categories", []))
            category_ids = set(supplement_categories(tree, "food") + supplement_categories(tree, "living"))
            sources = [("/openapi/products/today-deals", 30),
                       ("/openapi/products/best-selling", 100)]
            sources += [(f"/openapi/products/best-categories/{cid}", 20) for cid in sorted(category_ids)]
            snapshot = {"updated_at": now.isoformat(), "categories": categories,
                        "items": {}, "lists": {}, "links": dict(store.read().get("links", {}))}
            for path, size in sources:
                items = get(path, size).get("success", {}).get("items", [])
                snapshot["lists"][path] = [int(i["tacaItemId"]) for i in items]
                for item in items:
                    key = str(item["tacaItemId"])
                    # Retain expiry from the deals endpoint when lists overlap.
                    snapshot["items"][key] = {**snapshot["items"].get(key, {}), **item}
            publisher = api._config("TOSS_PUBLISHER_ID")
            today_ids = set(snapshot["lists"]["/openapi/products/today-deals"])
            for key, item in snapshot["items"].items():
                if not store.available(item, snapshot) or not item.get("displayPrice") or not item.get("thumbnailUrl"):
                    continue
                if int(key) not in today_ids and not any(classify(item, tree, cid) for cid in ("food", "living")):
                    continue
                link_key = key + ":" + publisher
                if link_key not in snapshot["links"]:
                    time.sleep(.12)
                    body = api._post_live_sync("/openapi/links", {"tacaItemId": int(key), "publisherId": publisher})
                    url = body.get("success", {}).get("shortUrl")
                    if not url:
                        raise api.TossSharelinkError("TOSS_LINK_URL_MISSING")
                    snapshot["links"][link_key] = url
                    # Retain issued links even if a later call fails.
                    saved = store.read()
                    saved["links"] = snapshot["links"]
                    store.write(saved)
            store.write(snapshot)
            state.update(status="ok", product_count=len(snapshot["items"]), updated_at=now.isoformat())
        except Exception as exc:
            # Log only known codes, never HTTP bodies, credentials or user data.
            quota = isinstance(exc, api.TossSharelinkError) and str(exc) in {
                "SHARELINK_OPENAPI_QUOTA_EXCEEDED", "LOCAL_DAILY_BUDGET_EXCEEDED"}
            state.update(status="quota_exceeded" if quota else "failed", blocked=quota)
            log.warning("Product collection stopped: %s", state["status"])
        store.write(state, STATE)
        return state["status"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        result = collect()
        if result != "not_due":
            log.info("Product collection: %s", result)
        if args.once:
            return
        time.sleep(60)


if __name__ == "__main__":
    main()
