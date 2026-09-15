"""Collection boundaries and diversity, based on Toss category ID paths."""
import math
from collections import Counter

ROOTS = {"생활용품": "생활", "주방용품": "주방", "가전/디지털": "가전/디지털",
         "문구/오피스": "문구", "뷰티": "뷰티/위생"}
LIVING_BRANCHES = {"구강/면도", "방충용품", "방향/탈취/제습/살충", "생활소품", "생활잡화",
                   "생활편의", "세제", "세탁용품", "수납/정리", "욕실용품", "청소용품",
                   "화장지/물티슈", "조명/전기용품", "생리대/성인기저귀"}
# Collapse variants of the same use, before falling back to the category branch.
FAMILIES = (
    ("탄산수", ("탄산수",)), ("생수", ("생수", "먹는샘물", "광천수")),
    ("탄산음료", ("탄산음료", "콜라", "사이다")),
    ("라면", ("라면",)), ("즉석밥", ("즉석밥",)),
    ("세탁세제", ("세탁세제",)), ("섬유유연제", ("섬유유연제",)),
    ("물티슈", ("물티슈",)), ("화장지", ("화장지", "두루마리")),
)
SMALL_APPLIANCES = ("소형", "이어폰", "헤드폰", "키보드", "마우스", "충전", "케이블",
                    "보조배터리", "스탠드", "선풍기", "전기포트", "토스터", "헤어", "면도기")


def classify(item, tree, collection_id):
    paths = [tree[int(cid)] for cid in item.get("categoryIds", []) if int(cid) in tree]
    food = any(path[0] == "식품" for path in paths)
    if collection_id == "food":
        paths = [p for p in paths if p[0] == "식품" and "전통주" not in p]
    else:
        if food:
            return None
        paths = [p for p in paths if p[0] in ROOTS]
        paths = [p for p in paths if p[0] != "생활용품" or (len(p) > 1 and p[1] in LIVING_BRANCHES)]
        paths = [p for p in paths if p[0] != "가전/디지털" or
                 any(word in " ".join(p[2:]) for word in SMALL_APPLIANCES)]
    if not paths:
        return None
    path = max(paths, key=lambda p: (len(p), tuple(p)))
    if len(path) < 3:
        return None  # Unknown types cannot bypass the diversity limits.
    group = path[1] if collection_id == "food" else ROOTS[path[0]]
    # Search deepest category first. A broad parent such as 생수/음료 must not
    # turn every child beverage into water.
    family = None
    for name in reversed(path[2:]):
        if name == "생수/탄산수":
            family = "탄산수" if "탄산수" in item.get("displayName", "") else "생수"
            break
        family = next((label for label, words in FAMILIES if any(w in name for w in words)), None)
        if family:
            break
    family = family or path[2]
    return {"group": group, "family": family, "category_paths": paths,
            "category_ids": item.get("categoryIds", [])}


def affinity_score(item, affinity):
    # Parent and child clicks describe one preference, not independent votes.
    strongest = max((max(0, affinity.get(int(cid), 0)) for cid in item.get("categoryIds", [])), default=0)
    return min(3.0, math.log1p(strongest))


def choose(items, selected, affinity, recent, limit=6):
    from app.services import recommendations as r
    counts = Counter(x["_policy"]["group"] for x in selected)
    families = {x["_policy"]["family"] for x in selected}
    available = [x for x in items if x["_policy"]["family"] not in families
                 and not x.get("isSoldOut") and not r._is_student_excluded(x)]
    eligible = [x for x in available if counts[x["_policy"]["group"]] < 2]
    relaxed = not eligible
    if not eligible:
        eligible = [x for x in available if counts[x["_policy"]["group"]] < 3]
    if not eligible:
        return None
    fresh = [x for x in eligible if int(x["tacaItemId"]) not in recent]
    eligible = fresh or eligible
    exploration = False
    if affinity and len(selected) == limit - 1:
        unexplored = [x for x in eligible if affinity_score(x, affinity) == 0]
        if unexplored:
            eligible = unexplored
            exploration = True
    def score(x):
        ranks = list((x.get("_source_ranks") or {}).values())
        rank = min(ranks) if ranks else int(x.get("rank") or 100)
        return (affinity_score(x, affinity) + 2 / max(rank, 1) ** .5
                + r._student_fit_score(x) + r._candidate_source_score(x))
    if fresh:
        winner = max(eligible, key=score)
    else:
        winner = min(eligible, key=lambda x: (recent[int(x["tacaItemId"])], -score(x)))
    winner = dict(winner)
    winner["_decision"] = {**winner["_policy"], "score": round(score(winner), 3),
                           "affinity_score": round(affinity_score(winner, affinity), 3),
                           "reason": "새 품목 탐색" if exploration else "미노출 우선" if fresh else "오래된 노출 순환",
                           "group_limit": 3 if relaxed else 2}
    return winner


def supplement_categories(tree, collection_id):
    """Round-robin across groups, never just the first deepest category."""
    groups = {}
    for cid, path in sorted(tree.items(), key=lambda p: (len(p[1]), p[0])):
        if len(path) != 3:
            continue
        policy = classify({"categoryIds": [cid]}, tree, collection_id)
        if policy:
            groups.setdefault((policy["group"], path[1]), []).append((cid, policy["family"]))
    result, families = [], set()
    for offset in range(max((len(v) for v in groups.values()), default=0)):
        for entries in groups.values():
            if offset < len(entries):
                cid, family = entries[offset]
                if family not in families:
                    result.append(cid)
                    families.add(family)
                    if len(result) == 18:
                        return result
    return result
