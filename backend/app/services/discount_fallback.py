"""Saved, bounded discount recommendations when day-deals are unavailable."""
import os
from collections import Counter

from app.services import product_snapshot as store, recommendation_policy as policy, recommendations


def candidates(snapshot=None):
    snapshot = store.read() if snapshot is None else snapshot
    tree = {}

    def walk(nodes, parent=()):
        for node in nodes:
            path = [*parent, node['displayName']]
            tree[int(node['categoryId'])] = path
            walk(node.get('children', []), path)

    walk(snapshot.get('categories', {}).get('success', {}).get('categories', []))
    publisher = os.environ.get('TOSS_PUBLISHER_ID', '')
    result = []
    for key, item in snapshot.get('items', {}).items():
        if not store.available(item, snapshot) or not item.get('thumbnailUrl'):
            continue
        try:
            price, original = int(item.get('displayPrice') or 0), int(item.get('originalPrice') or 0)
            # Cap exaggerated or inconsistent API rates at the price-derived rate.
            rate = min(int(item.get('discountRate') or 0), (original - price) * 100 // original)
        except (ValueError, TypeError, ZeroDivisionError):
            continue
        link = snapshot.get('links', {}).get(key + ':' + publisher)
        if not 0 < price <= 50000 or rate < 30 or not link:
            continue
        classified = policy.classify(item, tree, 'food') or policy.classify(item, tree, 'living')
        if not classified:
            continue
        names = [n for p in classified['category_paths'] for n in p]
        if recommendations._is_student_excluded(dict(item, _category_names=names)):
            continue
        result.append(dict(item, _policy=classified, _fallback_url=link, discountRate=rate))
    return result


def choose(items, recent, limit=6):
    selected, families, groups = [], set(), Counter()
    # Prefer >=40%; relax the rate only after trying the primary tier.
    for floor in (40, 30):
        for cap in (2, 3):
            eligible = [i for i in items if i['discountRate'] >= floor]
            eligible.sort(key=lambda i: (
                int(i['tacaItemId']) in recent,
                recent.get(int(i['tacaItemId']), 0),
                -i['discountRate'], i['displayPrice'], int(i['tacaItemId'])))
            for item in eligible:
                family, group = item['_policy']['family'], item['_policy']['group']
                if family in families or groups[group] >= cap:
                    continue
                selected.append(item)
                families.add(family)
                groups[group] += 1
                if len(selected) >= limit:
                    return selected
    return selected
