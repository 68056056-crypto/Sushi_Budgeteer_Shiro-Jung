"""
optimizer.py — DP Knapsack + Scoring สำหรับ Sushi-Budgeteer

อธิบาย algorithm:
  - ใช้ 0/1 Knapsack DP (แต่ละเมนูเลือกได้ครั้งเดียว)
  - capacity = budget (บาท)
  - value    = score ที่คำนวณจาก preference + budget fit + variety
  - weight   = price_baht

Random baseline อยู่ที่ random_baseline() เพื่อใช้เปรียบเทียบเท่านั้น
"""

from __future__ import annotations

import random
from typing import Any


# ---------------------------------------------------------------------------
# Scoring function — ใช้ก่อน DP เพื่อให้ DP เลือกตาม "คุ้มค่า" จริง
# ---------------------------------------------------------------------------

def score_item(
    row: Any,          # pandas Series หรือ dict
    preferred_keywords: list[str],
    budget: int,
    is_disliked: bool = False,
) -> float:
    """
    คำนวณ score ของ 1 เมนู (0–10)

    มิติที่ 1 — Preference Score (0–5):
        เมนูที่ตรง keyword ที่ผู้ใช้ชอบได้คะแนนสูงขึ้น

    มิติที่ 2 — Price Efficiency Score (0–3):
        ราคาไม่แพงเกินไปและไม่ถูกเกินจนไม่มีคุณภาพ
        peak ที่ราคา 40–80 บาท (ช่วงคุ้มค่าหลักของ Sushiro)

    มิติที่ 3 — Category Diversity Bonus (0–2):
        เมนูหมวดที่แตกต่างจาก "ปลาดิบ" เพิ่ม diversity

    Penalty: is_disliked → ลด 3 คะแนน (แต่ยังไม่ติดลบ)
    """
    if isinstance(row, dict):
        get = lambda k: row.get(k, "")
    else:
        get = lambda k: getattr(row, k, "") if hasattr(row, k) else row.get(k, "")

    name_th   = str(get("name_th") or "").lower()
    name_en   = str(get("name_en") or "").lower()
    keywords  = str(get("keywords") or "").lower()
    category  = str(get("category") or "")
    price     = float(get("price_baht") or 0)

    # --- Preference score ---
    pref_score = 0.0
    if preferred_keywords:
        text = f"{name_th} {name_en} {keywords}"
        matches = sum(1 for kw in preferred_keywords if kw in text)
        # สูงสุด 5 คะแนน
        pref_score = min(5.0, matches * 2.5)

    # --- Price efficiency score ---
    # ราคาในช่วง 40–80 ได้คะแนนเต็ม, ราคา 0 (ฟรี) ได้ 1, > 100 ลดลง
    if price == 0:
        price_score = 1.0
    elif 35 <= price <= 80:
        price_score = 3.0
    elif price <= 100:
        price_score = 2.0
    else:
        price_score = 1.0

    # --- Category diversity bonus ---
    diversity_bonus = 0.0
    non_raw = {"ปรุงสุก", "มากิ/โรล", "ของทอด", "ซุป", "ของหวาน", "เครื่องดื่ม", "ชุดเซ็ต"}
    if category in non_raw:
        diversity_bonus = 2.0

    total = pref_score + price_score + diversity_bonus

    # --- Dislike penalty ---
    if is_disliked:
        total = max(0.0, total - 3.0)

    return round(total, 3)


# ---------------------------------------------------------------------------
# DP Knapsack — 0/1 แบบ item ไม่ซ้ำ
# ---------------------------------------------------------------------------

def dp_knapsack(
    items: list[dict],
    budget: int,
    max_items: int = 20,
) -> list[dict]:
    """
    เลือกเมนูที่ได้ total score สูงสุดโดยไม่เกิน budget
    แต่ละเมนูเลือกได้ครั้งเดียว (0/1 Knapsack)

    จำกัดด้วย max_items เพื่อไม่ให้จาน overflow

    Args:
        items:     list[dict] แต่ละ item ต้องมี "price_baht" และ "score"
        budget:    งบประมาณสูงสุด (บาท)
        max_items: จำนวนจานสูงสุด

    Returns:
        list[dict] รายการที่ถูกเลือก
    """
    n = len(items)
    if n == 0 or budget <= 0:
        return []

    # DP table: dp[i][w] = (max_score, item_count) เมื่อพิจารณา i items แรก, capacity = w
    # ใช้ list of tuples (score, count) เพื่อ tie-break ด้วย count
    INF_NEG = (-1e9, 0)
    dp = [[INF_NEG] * (budget + 1) for _ in range(n + 1)]
    dp[0][0] = (0.0, 0)

    for i in range(1, n + 1):
        item = items[i - 1]
        price = int(item["price_baht"])
        score = float(item["score"])

        for w in range(budget + 1):
            # ไม่เลือก item i
            dp[i][w] = dp[i - 1][w]

            # เลือก item i (ถ้าจุ)
            if w >= price and dp[i - 1][w - price] != INF_NEG:
                prev_score, prev_count = dp[i - 1][w - price]
                new_score = prev_score + score
                new_count = prev_count + 1

                if new_count <= max_items:
                    curr_score, curr_count = dp[i][w]
                    # เลือก option ที่ score สูงกว่า; ถ้าเท่ากันเลือก count มากกว่า
                    if curr_score == INF_NEG or new_score > curr_score or (
                        abs(new_score - curr_score) < 1e-9 and new_count > curr_count
                    ):
                        dp[i][w] = (new_score, new_count)

    # Traceback — หาชุดที่ดีที่สุด
    best_w = max(range(budget + 1), key=lambda w: dp[n][w])
    if dp[n][best_w] == INF_NEG:
        return []

    selected = []
    w = best_w
    for i in range(n, 0, -1):
        if dp[i][w] != dp[i - 1][w]:
            selected.append(items[i - 1])
            w -= int(items[i - 1]["price_baht"])

    return selected


# ---------------------------------------------------------------------------
# Random Baseline — ใช้เฉพาะเปรียบเทียบ ไม่ใช่ decision จริง
# ---------------------------------------------------------------------------

def random_baseline(
    items: list[dict],
    budget: int,
    seed: int = 42,
) -> dict[str, Any]:
    """
    สร้างชุดเมนูแบบสุ่ม (random) เพื่อเปรียบเทียบกับ DP

    ใช้เฉพาะเป็น baseline เท่านั้น — ไม่ใช้เป็น decision หลัก

    Args:
        items:  list[dict] เมนูที่ผ่าน filter แล้ว
        budget: งบประมาณ
        seed:   random seed เพื่อ reproducibility

    Returns:
        {"selected_items": [...], "total_price": int, "total_score": float, "method": "random"}
    """
    rng = random.Random(seed)
    shuffled = items[:]
    rng.shuffle(shuffled)

    selected = []
    remaining = budget
    for item in shuffled:
        if item["price_baht"] <= remaining:
            selected.append(item)
            remaining -= item["price_baht"]

    total_price = sum(i["price_baht"] for i in selected)
    total_score = sum(i.get("score", 0) for i in selected)

    clean = [
        {k: v for k, v in item.items() if k not in ("score", "is_disliked", "allergen_set")}
        for item in selected
    ]

    return {
        "selected_items": clean,
        "total_price": total_price,
        "total_score": round(total_score, 3),
        "item_count": len(clean),
        "method": "random_baseline",
    }


# ---------------------------------------------------------------------------
# Comparison helper
# ---------------------------------------------------------------------------

def compare_dp_vs_random(
    items: list[dict],
    budget: int,
    max_items: int = 20,
    seed: int = 42,
) -> dict[str, Any]:
    """
    เรียก DP และ Random พร้อมกัน แล้ว return ผลเปรียบเทียบ
    ใช้ใน demo/presentation เพื่อแสดงว่า DP ดีกว่า random อย่างไร
    """
    dp_result = dp_knapsack(items=items, budget=budget, max_items=max_items)
    rand_result = random_baseline(items=items, budget=budget, seed=seed)

    dp_total = sum(i["price_baht"] for i in dp_result)
    dp_score = round(sum(i.get("score", 0) for i in dp_result), 3)

    return {
        "dp": {
            "selected_items": [
                {k: v for k, v in i.items() if k not in ("score", "is_disliked", "allergen_set")}
                for i in dp_result
            ],
            "total_price": dp_total,
            "total_score": dp_score,
            "item_count": len(dp_result),
            "method": "dp_knapsack",
        },
        "random": rand_result,
        "improvement": {
            "score_gain": round(dp_score - rand_result["total_score"], 3),
            "score_gain_pct": round(
                (dp_score - rand_result["total_score"]) / max(rand_result["total_score"], 1e-9) * 100, 1
            ),
        },
    }
