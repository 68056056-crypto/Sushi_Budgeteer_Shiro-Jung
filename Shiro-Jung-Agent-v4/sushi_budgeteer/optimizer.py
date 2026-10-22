"""SQLite-backed menu access, value scoring, and exact bounded Knapsack DP.

This module has no dependency on LangChain/LangGraph or any LLM — it is pure
Python + pandas, which makes it independently testable (see test_smoke.py).
"""

from __future__ import annotations

import json
import os
import random
from threading import local
from math import gcd, isfinite
from functools import reduce
from .database import records, cents
from .optimization_config import NEAR_BUDGET_PERCENT
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

import pandas as pd

# Compatibility only for legacy direct tools. Production MCP uses result IDs.
_last_result = local()


def set_last_result(result: Dict[str, Any]) -> None:
    _last_result.result = result


def get_last_result() -> Optional[Dict[str, Any]]:
    return getattr(_last_result, 'result', None)


# ----------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------
def load_menu(force_reload: bool = False) -> pd.DataFrame:
    """Load (and cache) the Sushiro menu dataset as a DataFrame."""
    return pd.DataFrame(records())


def menu_records(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Read the current SQLite catalog; no process-global menu snapshot."""
    return records()


# ----------------------------------------------------------------------
# Small text-matching helpers shared by scoring / filtering / RAG
# ----------------------------------------------------------------------
def parse_allergen_tags(cell: Any) -> Set[str]:
    """Split the `allergen_tags` cell ("fish;soy") into a tag set."""
    if not cell:
        return set()
    return {tag.strip().lower() for tag in str(cell).split(";") if tag.strip()}


def _searchable_text(row: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(row.get("name_th", "")),
            str(row.get("name_en", "")),
            str(row.get("keywords", "")),
            str(row.get("category", "")),
        ]
    ).lower()


def _levenshtein(a: str, b: str) -> int:
    """Classic edit distance, no external dependency needed for short strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def fuzzy_contains(text: str, keyword: str) -> bool:
    """Substring match with two fallbacks for how people actually phrase things.

    1. A small Levenshtein-distance tolerance over a sliding window — catches
       typos, e.g. "เซลมอน" instead of "แซลมอน" (a slipped leading vowel).
    2. A trailing-suffix fallback for Thai compound phrases: Thai has no word
       boundaries, and a user says "ของดิบ" (raw food/stuff) while the menu's
       category is "ปลาดิบ" (raw fish) — neither contains the other whole, but
       both share the meaningful root "ดิบ" (raw) at the end. Without this,
       "ของดิบ" as a hard_exclude_keyword matches nothing and silently
       excludes zero items, letting every raw dish straight through.
    """
    if not keyword:
        return False
    if keyword in text:
        return True
    if len(keyword) < 3:
        return False
    tolerance = 1 if len(keyword) <= 6 else 2
    n = len(keyword)
    for start in range(0, max(1, len(text) - n + 1)):
        if _levenshtein(keyword, text[start : start + n]) <= tolerance:
            return True
    # Compound-word fallback: try the keyword's trailing root (e.g. "ดิบ" out
    # of "ของดิบ") as a plain substring — exact match only, to keep this from
    # over-triggering on short generic suffixes.
    if len(keyword) >= 5:
        for suffix_len in range(len(keyword) - 1, 2, -1):
            if keyword[-suffix_len:] in text:
                return True
    return False


def matches_any_keyword(row: Dict[str, Any], keywords: Iterable[str]) -> bool:
    """True if any keyword fuzzy-matches (substring, or a small typo away) the row."""
    text = _searchable_text(row)
    for kw in keywords or []:
        kw = str(kw).strip().lower()
        if kw and fuzzy_contains(text, kw):
            return True
    return False


# ----------------------------------------------------------------------
# 4.2.1  score_item() — preference/price/category heuristic (0-17)
# ----------------------------------------------------------------------
def score_components(
    row: Dict[str, Any],
    preferred_keywords: Optional[Iterable[str]] = None,
    budget: Optional[float] = None,  # reserved for future budget-relative scoring
    is_disliked: bool = False,
) -> dict:
    """Combine item heuristics; budget proximity is a separate set-level objective.

    - Preference Score (0-12): 6 points per matching preferred keyword; a single
      preference outweighs the maximum combined price/category bonus of 5.
    - Price Efficiency Score (0-3): sweet spot 35-80 THB = 3, <=100 THB = 2,
      otherwise 1.
    - Legacy category weight (0-2, NOT set-level category coverage): +2 for any category other than raw fish
      ("ปลาดิบ"), to encourage a varied set instead of an all-sashimi plate.
    - Dislike Penalty (-3): applied last, floored at 0.
    """
    preferred_keywords = list(preferred_keywords or [])
    price = float(row.get("price_baht", 0.0))
    category = str(row.get("category", ""))
    text = _searchable_text(row)

    matches = sum(
        1
        for kw in preferred_keywords
        if str(kw).strip().lower() and fuzzy_contains(text, str(kw).strip().lower())
    )
    pref_score = min(12.0, matches * 6.0)

    if 35 <= price <= 80:
        price_score = 3.0
    elif price <= 100:
        price_score = 2.0
    else:
        price_score = 1.0

    diversity_bonus = 2.0 if category != "ปลาดิบ" else 0.0

    total = pref_score + price_score + diversity_bonus
    if is_disliked:
        total = max(0.0, total - 3.0)
    return {'preference':pref_score,'price_efficiency':price_score,
            'category_bonus':diversity_bonus,'dislike_penalty':3.0 if is_disliked else 0.0,
            'total':round(total,3)}


def score_item(row, preferred_keywords=None, budget=None, is_disliked=False):
    return score_components(row,preferred_keywords,budget,is_disliked)['total']


# ----------------------------------------------------------------------
# Exact bounded dp_knapsack() — bounded Knapsack via Dynamic Programming
# ----------------------------------------------------------------------
def dp_knapsack(items, budget, max_items=20, max_repeat_per_item=3, min_items=0, objective="score", diversity=False, required_keywords=None):
    """Exact bounded knapsack: score first, actual spend second; count is a DP dimension."""
    if not 1 <= max_repeat_per_item <= 10:
        raise ValueError("repeat cap ต้องอยู่ระหว่าง 1–10")
    expanded=[]
    for item in items:
        for repeat in range(max_repeat_per_item):
            copy=dict(item)
            if diversity:
                copy['score']=float(item['score'])*(0.5**repeat)
            expanded.append(copy)
    return _dp_knapsack_01(expanded,budget,max_items=max_items,min_items=min_items,objective=objective,required_keywords=required_keywords)


def _dp_knapsack_01(items, budget, max_items=20, min_items=0, objective="score", required_keywords=None):
    required_keywords=list(dict.fromkeys(required_keywords or []))
    if len(required_keywords)>8: raise ValueError("ขอเมนูที่ต้องมีได้ไม่เกิน 8 รายการ")
    complete=(1 << len(required_keywords))-1
    if objective not in {"score", "budget"}:
        raise ValueError("unknown optimization objective")
    cap = cents(budget)
    if cap > 10_000_000 or not 0 <= min_items <= max_items <= 60 or len(items)>1500:
        raise ValueError("เกินขอบเขต: งบไม่เกิน 100000 บาท จำนวนรายการไม่เกิน 60")
    if max_items == 0 or not items:
        return []
    prices = [cents(x['price_baht']) for x in items]
    scale = reduce(gcd, (p for p in prices if p), 0) or 1
    capacity = cap // scale
    # Immutable paths make backtracking valid even after a state is replaced.
    states = {(0, 0, 0): (0.0, ())}
    for i, item in enumerate(items):
        price, score = prices[i] // scale, float(item['score'])
        if not isfinite(score):
            raise ValueError("score ต้องเป็นจำนวนจำกัด")
        coverage=sum(1 << bit for bit,keyword in enumerate(required_keywords) if matches_any_keyword(item,[keyword]))
        for (count, cost, covered), (value, path) in list(states.items()):
            if count >= max_items or cost + price > capacity:
                continue
            key = (count + 1, cost + price, covered | coverage)
            candidate = (value + score, path + (i,))
            if key not in states or candidate[0] > states[key][0]:
                states[key] = candidate
        if len(states) > 250_000:
            raise ValueError("DP state limit: กรุณาลดงบ/จำนวนรายการ")
    feasible = [(value, cost, path) for (count,cost,covered),(value,path) in states.items()
                if min_items <= count <= max_items and covered == complete]
    if not feasible:
        return []
    if objective == "budget":
        # Meet a useful budget band first, then retain the original preference objective.
        # Compare integer satang against the actual budget, never a rounded/scaled target.
        near=[entry for entry in feasible if entry[1]*scale*100 >= cap*NEAR_BUDGET_PERCENT]
        if near:
            _, _, path=max(near,key=lambda x:(x[0],x[1]))
        else:
            _, _, path=max(feasible,key=lambda x:(x[1],x[0]))
    else:
        _, _, path = max(feasible, key=lambda x:(x[0],x[1]))
    return [items[i] for i in path]


def aggregate_by_item_id(
    selected: List[Dict[str, Any]],
    brief_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Collapse repeats of the same dish (dp_knapsack may pick the same
    item_id more than once, up to max_repeat_per_item) into one entry with a
    `quantity` + `subtotal_baht`, so a response reads "ซูชิแซลมอน x2 - 80 บาท"
    instead of listing the same dish twice. `brief_fn` lets callers (tools.py,
    other adapters) control which fields end up in each entry; defaults to a shallow
    copy of the full item dict.
    """
    brief_fn = brief_fn or (lambda item: dict(item))
    order: List[str] = []
    grouped: Dict[str, Dict[str, Any]] = {}
    for item in selected:
        item_id = item.get("item_id")
        if item_id not in grouped:
            order.append(item_id)
            brief = brief_fn(item)
            brief["quantity"] = 0
            brief["subtotal_baht"] = 0.0
            grouped[item_id] = brief
        grouped[item_id]["quantity"] += 1
        grouped[item_id]["subtotal_baht"] = round(
            grouped[item_id]["quantity"] * float(item.get("price_baht", 0.0)), 2
        )
    return [grouped[item_id] for item_id in order]


# ----------------------------------------------------------------------
# 4.2.3  random_baseline() / compare_dp_vs_random()
# ----------------------------------------------------------------------
def random_baseline(
    items: List[Dict[str, Any]],
    budget: float,
    max_items: int = 20,
    seed: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Greedy-random baseline: shuffle items, keep grabbing until the budget
    or the item-count cap runs out. Used only for comparison/demo purposes —
    never returned to the user as an actual recommendation.
    """
    rng = random.Random(seed)
    pool = items[:]
    rng.shuffle(pool)

    selected: List[Dict[str, Any]] = []
    remaining = float(budget)
    for item in pool:
        if len(selected) >= max_items:
            break
        price = float(item["price_baht"])
        if price <= remaining:
            selected.append(item)
            remaining -= price
    return selected


def compare_dp_vs_random(
    items: List[Dict[str, Any]],
    budget: float,
    max_items: int = 20,
    seed: Optional[int] = None,
) -> Dict[str, Any]:
    """Run both algorithms on the same item pool and report the score gap."""
    dp_selected = dp_knapsack(items, budget, max_items=max_items)
    random_selected = random_baseline([x for x in items for _ in range(3)], budget, max_items=max_items, seed=seed)

    dp_score = round(sum(float(it["score"]) for it in dp_selected), 3)
    random_score = round(sum(float(it["score"]) for it in random_selected), 3)
    dp_total = round(sum(float(it["price_baht"]) for it in dp_selected), 2)
    random_total = round(sum(float(it["price_baht"]) for it in random_selected), 2)

    if random_score > 0:
        gain_pct = round((dp_score - random_score) / random_score * 100, 2)
    else:
        gain_pct = 100.0 if dp_score > 0 else 0.0

    return {
        "dp": {"items": dp_selected, "total_score": dp_score, "total_price": dp_total},
        "random": {"items": random_selected, "total_score": random_score, "total_price": random_total},
        "score_gain_pct": gain_pct,
    }
