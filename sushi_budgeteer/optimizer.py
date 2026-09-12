"""Core algorithm layer: menu loading, value scoring, and 0/1 Knapsack DP.

This module has no dependency on LangChain/LangGraph or any LLM — it is pure
Python + pandas, which makes it independently testable (see test_smoke.py).
"""

from __future__ import annotations

import json
import os
import random
from typing import Any, Callable, Dict, Iterable, List, Optional, Set

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The CSV has moved around during project reorganization (e.g. into a
# "Presentation and Data Base" folder alongside the report/slides), so check
# a few likely spots instead of assuming one fixed layout. Override with the
# SUSHI_MENU_CSV_PATH env var if it ends up somewhere else entirely.
_CSV_FILENAME = "sushiro_menu_dataset.csv"
_CSV_CANDIDATES = [
    os.environ.get("SUSHI_MENU_CSV_PATH", ""),
    os.path.join(_PROJECT_ROOT, "Presentation and Data Base", _CSV_FILENAME),
    os.path.join(_PROJECT_ROOT, _CSV_FILENAME),
    os.path.join(_PROJECT_ROOT, "data", _CSV_FILENAME),
]


def _resolve_data_path() -> str:
    for candidate in _CSV_CANDIDATES:
        if candidate and os.path.isfile(candidate):
            return candidate
    raise FileNotFoundError(
        f"{_CSV_FILENAME} not found. Checked: "
        + ", ".join(c for c in _CSV_CANDIDATES if c)
        + ". Set the SUSHI_MENU_CSV_PATH environment variable to its exact path if it moved elsewhere."
    )


_menu_cache: Optional[pd.DataFrame] = None

# Shared "last computed set" cache. build_optimal_set() and
# rag_augmented_build() both write here so that verify_result() can re-check
# whichever one ran most recently, without the LLM having to restate the
# full selected-item list as a tool argument.
_last_result_cache: Dict[str, Any] = {"result": None}


def set_last_result(result: Dict[str, Any]) -> None:
    _last_result_cache["result"] = result


def get_last_result() -> Optional[Dict[str, Any]]:
    return _last_result_cache["result"]


# ----------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------
def load_menu(force_reload: bool = False) -> pd.DataFrame:
    """Load (and cache) the Sushiro menu dataset as a DataFrame."""
    global _menu_cache
    if _menu_cache is None or force_reload:
        df = pd.read_csv(_resolve_data_path())
        df["price_baht"] = df["price_baht"].astype(float)
        df["allergens_verified"] = df["allergens_verified"].fillna("")
        df["keywords"] = df["keywords"].fillna("")
        df["description_th"] = df["description_th"].fillna("")
        _menu_cache = df
    return _menu_cache.copy()


def menu_records(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Return the menu as a list of plain dicts (one per row).

    Round-trips through DataFrame.to_json()/json.loads() instead of plain
    .to_dict() — pandas' own to_dict() leaves numeric columns as numpy
    scalars (numpy.float64/int64), which json.dumps() cannot serialize, and
    every tool in this project immediately json.dumps() these rows.
    """
    df = load_menu(force_reload=force_reload)
    return json.loads(df.to_json(orient="records", force_ascii=False))


# ----------------------------------------------------------------------
# Small text-matching helpers shared by scoring / filtering / RAG
# ----------------------------------------------------------------------
def parse_allergen_tags(cell: Any) -> Set[str]:
    """Split the `allergens_verified` cell ("fish;soy") into a tag set."""
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
# 4.2.1  score_item() — value-for-money scoring (0-10)
# ----------------------------------------------------------------------
def score_item(
    row: Dict[str, Any],
    preferred_keywords: Optional[Iterable[str]] = None,
    budget: Optional[float] = None,  # reserved for future budget-relative scoring
    is_disliked: bool = False,
) -> float:
    """Combine 3 dimensions: preference + price efficiency + diversity.

    - Preference Score (0-5): 2.5 points per matching preferred keyword.
    - Price Efficiency Score (0-3): sweet spot 35-80 THB = 3, <=100 THB = 2,
      otherwise 1.
    - Category Diversity Bonus (0-2): +2 for any category other than raw fish
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
    pref_score = min(5.0, matches * 2.5)

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
    return round(total, 3)


# ----------------------------------------------------------------------
# 4.2.2  dp_knapsack() — 0/1 Knapsack via Dynamic Programming
# ----------------------------------------------------------------------
def dp_knapsack(
    items: List[Dict[str, Any]],
    budget: float,
    max_items: int = 20,
    max_repeat_per_item: int = 3,
) -> List[Dict[str, Any]]:
    """Pick the multiset of `items` with the highest total `score` that fits
    within `budget` baht.

    Each *distinct* item may be chosen up to `max_repeat_per_item` times —
    like a real conveyor-belt sushi order, taking a second or third plate of
    a favorite dish is normal, and allowing repeats lets the optimizer land
    much closer to the target budget than a strict 0/1 (one-of-each) choice
    would. Implemented as plain 0/1 knapsack over an expanded pool where each
    item appears `max_repeat_per_item` times — repeats of the same item may
    appear multiple times in the returned list; aggregate by item_id for a
    "x2/x3" quantity display.

    Each item in `items` must already carry a numeric `score` field (from
    `score_item`) and a `price_baht` field. Returns the optimal multiset of
    the original item dicts (global optimum, not an approximation).

    Time complexity: O(n * max_repeat_per_item * budget).
    """
    expanded_items = [item for item in items for _ in range(max(1, max_repeat_per_item))]
    return _dp_knapsack_01(expanded_items, budget, max_items=max_items)


def _dp_knapsack_01(
    items: List[Dict[str, Any]],
    budget: float,
    max_items: int = 20,
) -> List[Dict[str, Any]]:
    """Plain 0/1 knapsack: each entry in `items` chosen at most once.

    `dp_knapsack()` builds repeat-capable results on top of this by expanding
    the item pool beforehand; this function itself has no notion of repeats.
    """
    n = len(items)
    cap = max(0, int(round(budget)))

    # dp[i][w] = (best achievable score, number of items used) considering
    # only the first i items with capacity w.
    dp: List[List[Any]] = [[(0.0, 0)] * (cap + 1) for _ in range(n + 1)]
    take: List[List[bool]] = [[False] * (cap + 1) for _ in range(n + 1)]

    for i in range(1, n + 1):
        price = max(0, int(round(items[i - 1]["price_baht"])))
        score = float(items[i - 1]["score"])
        row_prev = dp[i - 1]
        row_cur = dp[i]
        take_cur = take[i]
        for w in range(cap + 1):
            row_cur[w] = row_prev[w]
            if price <= w:
                prev_score, prev_count = row_prev[w - price]
                new_count = prev_count + 1
                if new_count <= max_items:
                    new_score = prev_score + score
                    if new_score > row_cur[w][0]:
                        row_cur[w] = (new_score, new_count)
                        take_cur[w] = True

    # Prefer the highest score; break ties by using more of the budget.
    best_w = max(range(cap + 1), key=lambda w: (dp[n][w][0], w))

    selected: List[Dict[str, Any]] = []
    w = best_w
    for i in range(n, 0, -1):
        if take[i][w]:
            item = items[i - 1]
            selected.append(item)
            w -= max(0, int(round(item["price_baht"])))
    selected.reverse()
    return selected


def aggregate_by_item_id(
    selected: List[Dict[str, Any]],
    brief_fn: Optional[Callable[[Dict[str, Any]], Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Collapse repeats of the same dish (dp_knapsack may pick the same
    item_id more than once, up to max_repeat_per_item) into one entry with a
    `quantity` + `subtotal_baht`, so a response reads "ซูชิแซลมอน x2 - 80 บาท"
    instead of listing the same dish twice. `brief_fn` lets callers (tools.py,
    rag.py) control which fields end up in each entry; defaults to a shallow
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
    random_selected = random_baseline(items, budget, max_items=max_items, seed=seed)

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
