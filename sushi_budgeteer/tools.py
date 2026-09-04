"""
tools.py — Sushi-Budgeteer Agent Tools

แต่ละ Tool มีหน้าที่แยกกันชัดเจน:
  1. search_menu_items     — ค้นหาเมนูจาก keyword / category / ราคา
  2. filter_constraints    — กรองเมนูที่ขัดกับ allergen หรือ dislike ออก
  3. build_optimal_set     — จัดชุดเมนูให้คุ้มค่าด้วย DP / constrained optimization
  4. verify_result         — ตรวจสอบผลลัพธ์ก่อนส่งคำตอบ
  5. request_clarification — ถามผู้ใช้เมื่อข้อมูลไม่ครบ/ขัดแย้ง
"""

from __future__ import annotations

import os
import sys
import pandas as pd
from typing import Any
from langchain_core.tools import tool

# Ensure this package directory is on sys.path so sibling imports work
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# ---------------------------------------------------------------------------
# Dataset loader (singleton)
# ---------------------------------------------------------------------------

_MENU_DF: pd.DataFrame | None = None


def _load_menu() -> pd.DataFrame:
    global _MENU_DF
    if _MENU_DF is None:
        csv_path = os.path.join(_THIS_DIR, "..", "sushiro_menu_dataset.csv")
        csv_path = os.path.abspath(csv_path)
        df = pd.read_csv(csv_path)
        df["allergen_set"] = df["allergens_verified"].apply(
            lambda x: set(str(x).lower().split(";")) - {""} - {"nan"}
            if pd.notna(x) and str(x).strip() else set()
        )
        _MENU_DF = df
    return _MENU_DF


def _df_to_records(df: pd.DataFrame) -> list[dict]:
    """Return clean list of dicts (drop internal helper columns)."""
    return df.drop(columns=["allergen_set"], errors="ignore").to_dict(orient="records")


# ---------------------------------------------------------------------------
# Internal helper — reusable filter logic (not a Tool, called directly by
# build_optimal_set to avoid LangChain tool invocation overhead)
# ---------------------------------------------------------------------------

def _run_filter(
    allergens: list[str],
    dislikes: list[str],
    categories_wanted: list[str] | None,
) -> dict[str, Any]:
    """Pure Python filter — same logic as the filter_constraints Tool."""
    df = _load_menu().copy()

    allergens = [a.lower().strip() for a in allergens]
    dislikes_lower = [d.lower().strip() for d in dislikes]

    if categories_wanted:
        df = df[df["category"].isin(categories_wanted)]

    # Hard block: allergen
    allergen_mask = df["allergen_set"].apply(lambda s: bool(s & set(allergens)))
    allergen_blocked = df[allergen_mask]
    remaining = df[~allergen_mask]

    # Soft: dislike
    def is_disliked(row) -> bool:
        if not dislikes_lower:
            return False
        text = " ".join([
            str(row.get("name_th", "")),
            str(row.get("name_en", "")),
            str(row.get("keywords", "")),
            str(row.get("category", "")),
        ]).lower()
        return any(d in text for d in dislikes_lower)

    dislike_mask = remaining.apply(is_disliked, axis=1)
    dislike_items = remaining[dislike_mask]
    safe_items = remaining[~dislike_mask]

    return {
        "safe_items": _df_to_records(safe_items),
        "allergen_blocked": _df_to_records(allergen_blocked),
        "dislike_items": _df_to_records(dislike_items),
        "counts": {
            "safe": len(safe_items),
            "allergen_blocked": len(allergen_blocked),
            "dislike": len(dislike_items),
        },
    }


# ---------------------------------------------------------------------------
# Tool 1 — search_menu_items
# ---------------------------------------------------------------------------

@tool
def search_menu_items(
    keyword: str = "",
    category: str = "",
    max_price: int = 0,
    min_price: int = 0,
) -> dict[str, Any]:
    """
    ค้นหาเมนูในฐานข้อมูลซูชิโร่ตาม keyword, หมวดหมู่ (category), หรือช่วงราคา

    Args:
        keyword:   คำค้นหา (ชื่อเมนู / วัตถุดิบ) เช่น "แซลมอน", "salmon", "กุ้ง"
        category:  หมวดหมู่ เช่น "ปลาดิบ", "มากิ/โรล", "ของหวาน", "เครื่องดื่ม"
        max_price: ราคาสูงสุด (บาท) — ใส่ 0 หมายถึงไม่จำกัด
        min_price: ราคาต่ำสุด (บาท) — ใส่ 0 หมายถึงไม่จำกัด

    Returns:
        {"items": [...], "count": int}
    """
    df = _load_menu().copy()

    if keyword:
        kw = keyword.lower()
        mask = (
            df["name_th"].str.lower().str.contains(kw, na=False)
            | df["name_en"].str.lower().str.contains(kw, na=False)
            | df["keywords"].str.lower().str.contains(kw, na=False)
            | df["description_th"].str.lower().str.contains(kw, na=False)
        )
        df = df[mask]

    if category:
        df = df[df["category"].str.contains(category, case=False, na=False)]

    if max_price > 0:
        df = df[df["price_baht"] <= max_price]

    if min_price > 0:
        df = df[df["price_baht"] >= min_price]

    return {"items": _df_to_records(df), "count": len(df)}


# ---------------------------------------------------------------------------
# Tool 2 — filter_constraints
# ---------------------------------------------------------------------------

@tool
def filter_constraints(
    allergens: list[str] | None = None,
    dislikes: list[str] | None = None,
    categories_wanted: list[str] | None = None,
) -> dict[str, Any]:
    """
    กรองเมนูที่ขัดกับข้อจำกัดของผู้ใช้ออก

    ความแตกต่างสำคัญ:
      - allergens  : เมนูที่มี allergen เหล่านี้จะถูกตัดออกอย่างเด็ดขาด
                     (แพ้อาหาร — ความปลอดภัย)
      - dislikes   : เมนูที่มี keyword/category เหล่านี้จะถูกลดลำดับ
                     (ไม่ชอบ — preference เท่านั้น)
      - categories_wanted : ถ้าระบุ จะกรองเฉพาะหมวดที่ต้องการ

    Args:
        allergens:         list ของ allergen tags เช่น ["fish", "gluten"]
        dislikes:          list ของ keyword ที่ไม่ชอบ เช่น ["ปลาหมึก", "octopus"]
        categories_wanted: list ของหมวดที่ต้องการ เช่น ["ปลาดิบ", "ปรุงสุก"]

    Returns:
        {
          "safe_items":       [...],
          "allergen_blocked": [...],
          "dislike_items":    [...],
          "counts":           {...}
        }
    """
    return _run_filter(
        allergens=allergens or [],
        dislikes=dislikes or [],
        categories_wanted=categories_wanted,
    )


# ---------------------------------------------------------------------------
# Tool 3 — build_optimal_set  (DP + scoring)
# ---------------------------------------------------------------------------

@tool
def build_optimal_set(
    budget: int,
    preferred_keywords: list[str] | None = None,
    min_items: int = 1,
    max_items: int = 20,
    allergens: list[str] | None = None,
    dislikes: list[str] | None = None,
    require_categories: list[str] | None = None,
) -> dict[str, Any]:
    """
    จัดชุดเมนูที่คุ้มค่าที่สุดภายในงบประมาณ โดยใช้ Dynamic Programming

    คะแนนความคุ้มค่า (score) วัดจาก 3 มิติรวมกัน:
      1. preference_score (0-5): ตรงกับ keyword ที่ผู้ใช้ชอบมากแค่ไหน
      2. price_efficiency (0-3): ราคาอยู่ในช่วงคุ้มค่า 35-80 บาท
      3. variety_score    (0-2): ความหลากหลายของหมวดหมู่

    Algorithm: 0/1 Knapsack DP — capacity=budget, value=score, weight=price
    ไม่ใช้การสุ่ม (random) ในการตัดสินใจหลัก

    Args:
        budget:             งบประมาณสูงสุด (บาท)
        preferred_keywords: keyword ที่ผู้ใช้ชอบ เช่น ["แซลมอน", "กุ้ง"]
        min_items:          จำนวนจานขั้นต่ำที่ต้องการ
        max_items:          จำนวนจานสูงสุด
        allergens:          allergen ที่ต้องห้าม (กรองออกก่อน DP)
        dislikes:           keyword ที่ไม่ชอบ (ลด score)
        require_categories: บังคับให้มีหมวดนี้อย่างน้อย 1 รายการ

    Returns:
        {
          "selected_items":        [...],
          "total_price":           int,
          "budget":                int,
          "budget_utilization_pct": float,
          "total_score":           float,
          "item_count":            int,
          "categories_covered":   [...],
          "feasible":              bool,
          "message":               str
        }
    """
    from optimizer import dp_knapsack, score_item

    # Step 1: กรองข้อจำกัดก่อนส่งเข้า DP (เรียก internal helper โดยตรง)
    filter_result = _run_filter(
        allergens=allergens or [],
        dislikes=dislikes or [],
        categories_wanted=require_categories,
    )

    safe_df = pd.DataFrame(filter_result["safe_items"])
    dislike_df = pd.DataFrame(filter_result["dislike_items"])

    if safe_df.empty and dislike_df.empty:
        return {
            "selected_items": [],
            "total_price": 0,
            "budget": budget,
            "budget_utilization_pct": 0.0,
            "total_score": 0.0,
            "item_count": 0,
            "categories_covered": [],
            "feasible": False,
            "message": "ไม่มีเมนูที่ผ่านเงื่อนไข allergen กรุณาผ่อนคลายเงื่อนไข",
        }

    if not safe_df.empty:
        safe_df = safe_df.copy()
        safe_df["is_disliked"] = False
    if not dislike_df.empty:
        dislike_df = dislike_df.copy()
        dislike_df["is_disliked"] = True

    all_items_df = pd.concat(
        [df for df in [safe_df, dislike_df] if not df.empty],
        ignore_index=True,
    )

    preferred_keywords = [k.lower() for k in (preferred_keywords or [])]

    # Step 2: คำนวณ score ให้แต่ละรายการ
    items_with_score = []
    for _, row in all_items_df.iterrows():
        s = score_item(
            row=row,
            preferred_keywords=preferred_keywords,
            budget=budget,
            is_disliked=bool(row.get("is_disliked", False)),
        )
        items_with_score.append({**row.to_dict(), "score": s})

    # ตรวจว่างบพอสำหรับจานที่ถูกสุดไหม
    min_price = min(item["price_baht"] for item in items_with_score)
    if budget < min_price:
        return {
            "selected_items": [],
            "total_price": 0,
            "budget": budget,
            "budget_utilization_pct": 0.0,
            "total_score": 0.0,
            "item_count": 0,
            "categories_covered": [],
            "feasible": False,
            "message": (
                f"งบประมาณ {budget} บาท น้อยกว่าเมนูที่ถูกสุด ({min_price} บาท) "
                "กรุณาเพิ่มงบหรือลดข้อจำกัด"
            ),
        }

    # Step 3: DP Knapsack
    selected = dp_knapsack(items=items_with_score, budget=budget, max_items=max_items)

    total_price = sum(i["price_baht"] for i in selected)
    utilization = round(total_price / budget * 100, 1) if budget > 0 else 0.0
    categories = list({i["category"] for i in selected})

    clean_selected = [
        {k: v for k, v in item.items() if k not in ("score", "is_disliked", "allergen_set")}
        for item in selected
    ]

    if len(selected) < min_items:
        return {
            "selected_items": clean_selected,
            "total_price": total_price,
            "budget": budget,
            "budget_utilization_pct": utilization,
            "total_score": round(sum(i["score"] for i in selected), 3),
            "item_count": len(selected),
            "categories_covered": categories,
            "feasible": False,
            "message": (
                f"จัดได้เพียง {len(selected)} จาน ต้องการขั้นต่ำ {min_items} จาน "
                "กรุณาเพิ่มงบหรือลด min_items"
            ),
        }

    return {
        "selected_items": clean_selected,
        "total_price": total_price,
        "budget": budget,
        "budget_utilization_pct": utilization,
        "total_score": round(sum(i["score"] for i in selected), 3),
        "item_count": len(selected),
        "categories_covered": categories,
        "feasible": True,
        "message": f"จัดได้ {len(selected)} จาน รวม {total_price} บาท (ใช้งบ {utilization}%)",
    }


# ---------------------------------------------------------------------------
# Tool 4 — verify_result
# ---------------------------------------------------------------------------

@tool
def verify_result(
    selected_items: list[dict],
    budget: int,
    allergens: list[str] | None = None,
) -> dict[str, Any]:
    """
    ตรวจสอบผลลัพธ์ก่อนส่งให้ผู้ใช้ว่า:
      1. ยอดรวมไม่เกินงบ
      2. ไม่มีเมนูที่มี allergen ต้องห้ามหลุดออกไป
      3. มีรายการอย่างน้อย 1 รายการ

    Args:
        selected_items: รายการเมนูที่ถูกเลือก (list of dict)
        budget:         งบประมาณ (บาท)
        allergens:      allergen ที่ต้องห้าม

    Returns:
        {
          "passed":              bool,
          "total_price":         int,
          "within_budget":       bool,
          "allergen_violations": [...],
          "is_empty":            bool,
          "issues":              [str]
        }
    """
    allergens = [a.lower().strip() for a in (allergens or [])]
    df = _load_menu()

    total_price = sum(item.get("price_baht", 0) for item in selected_items)
    within_budget = total_price <= budget
    is_empty = len(selected_items) == 0

    # ตรวจ allergen จาก allergen_set ในฐานข้อมูล (ไม่ใช่จาก description)
    violations = []
    item_ids = [item.get("item_id") for item in selected_items if item.get("item_id")]
    if item_ids and allergens:
        matched = df[df["item_id"].isin(item_ids)]
        for _, row in matched.iterrows():
            overlap = row["allergen_set"] & set(allergens)
            if overlap:
                violations.append({
                    "item_id": row["item_id"],
                    "name_th": row["name_th"],
                    "allergens_found": list(overlap),
                })

    issues = []
    if is_empty:
        issues.append("ไม่มีเมนูในผลลัพธ์")
    if not within_budget:
        issues.append(f"ยอดรวม {total_price} บาท เกินงบ {budget} บาท")
    for v in violations:
        issues.append(
            f"เมนู '{v['name_th']}' มี allergen {v['allergens_found']} ซึ่งห้ามอยู่"
        )

    return {
        "passed": within_budget and not violations and not is_empty,
        "total_price": total_price,
        "within_budget": within_budget,
        "allergen_violations": violations,
        "is_empty": is_empty,
        "issues": issues,
    }


# ---------------------------------------------------------------------------
# Tool 5 — request_clarification
# ---------------------------------------------------------------------------

@tool
def request_clarification(reason: str, missing_fields: list[str]) -> dict[str, Any]:
    """
    สร้างข้อความถามผู้ใช้เพิ่มเติม เมื่อข้อมูลไม่ครบหรือขัดแย้งกัน

    ใช้เมื่อ:
      - ไม่มีงบประมาณ
      - งบน้อยเกินไปจนจัดเซ็ตไม่ได้
      - allergen ครอบคลุมทุกเมนูในหมวดที่ต้องการ

    Args:
        reason:         เหตุผลที่ต้องถาม
        missing_fields: list ของ field ที่ขาด เช่น ["budget", "allergens"]

    Returns:
        {"clarification_needed": True, "message": str, "missing_fields": [...]}
    """
    field_prompts = {
        "budget": "งบประมาณของคุณคือเท่าไหร่ (บาท)?",
        "allergens": "คุณแพ้อาหารอะไรบ้าง? (เช่น ปลา กุ้ง ไข่ กลูเตน)",
        "min_items": "ต้องการกี่จานขั้นต่ำ?",
        "preferences": "ชอบเมนูประเภทไหนเป็นพิเศษ?",
    }
    prompts = [field_prompts.get(f, f"กรุณาระบุ: {f}") for f in missing_fields]
    message = (
        f"ต้องการข้อมูลเพิ่มเติมเนื่องจาก: {reason}\n"
        + "\n".join(f"• {p}" for p in prompts)
    )
    return {
        "clarification_needed": True,
        "message": message,
        "missing_fields": missing_fields,
    }


# ---------------------------------------------------------------------------
# Export list for agent binding
# ---------------------------------------------------------------------------

# RAG tools import แบบ lazy เพื่อไม่ให้ crash ถ้า faiss ยังไม่ install
def _get_rag_tools() -> list:
    try:
        from rag import RAG_TOOLS
        return RAG_TOOLS
    except ImportError:
        return []

AGENT_TOOLS = [
    search_menu_items,
    filter_constraints,
    build_optimal_set,
    verify_result,
    request_clarification,
    *_get_rag_tools(),   # semantic_search_menu, rag_augmented_build
]
