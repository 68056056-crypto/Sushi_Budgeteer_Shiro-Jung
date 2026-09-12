"""LangChain Tools exposed to the ReAct Agent.

Each function below is decorated with @tool so that LangChain can turn its
signature + docstring into a JSON schema the LLM can read and call. The LLM
decides *which* tool to call, *when*, and *with what arguments* — this file
only implements what each tool actually does once called.

`build_optimal_set` stores its output in a module-level cache so that
`verify_result` (which the Agent must always call right afterwards) can
re-check the same computed set without the LLM having to restate the full
item list as arguments.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool

from .optimizer import (
    aggregate_by_item_id,
    dp_knapsack,
    fuzzy_contains,
    get_last_result,
    matches_any_keyword,
    menu_records,
    parse_allergen_tags,
    score_item,
    set_last_result,
)

# ----------------------------------------------------------------------
# Shared filtering logic (used by both filter_constraints and
# build_optimal_set, without going through the LLM/tool-call overhead twice)
# ----------------------------------------------------------------------
def _run_filter(
    menu: List[Dict[str, Any]],
    allergens: Optional[List[str]] = None,
    dislikes: Optional[List[str]] = None,
    hard_exclude_keywords: Optional[List[str]] = None,
    must_include_keywords: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split the menu into safe_items / removed_items / dislike_items.

    Hard constraints — never enter scoring or DP:
    - allergens: medical allergy tags, matched ONLY against allergens_verified.
    - hard_exclude_keywords: free-text dietary exclusions that are NOT medical
      allergens (e.g. "ของดิบ" raw food, "หมู" pork if not wanted at all) —
      matched against name/keywords/category, same as dislikes but hard.
    - must_include_keywords: when non-empty, ONLY items matching at least one
      of these survive ("กินแค่กุ้งกับปลา" = eat only shrimp and fish) —
      everything else is excluded outright, not merely deprioritized.

    Soft constraint — stays in the candidate pool, just flagged so
    score_item() can apply a score penalty rather than removing it:
    - dislikes.
    """
    allergens_norm = {str(a).strip().lower() for a in (allergens or []) if str(a).strip()}
    dislikes = dislikes or []
    hard_exclude_keywords = hard_exclude_keywords or []
    must_include_keywords = must_include_keywords or []

    safe_items: List[Dict[str, Any]] = []
    removed_items: List[Dict[str, Any]] = []
    dislike_items: List[Dict[str, Any]] = []

    for row in menu:
        row_allergens = parse_allergen_tags(row.get("allergens_verified"))
        if allergens_norm & row_allergens:
            removed_items.append(row)
            continue
        if hard_exclude_keywords and matches_any_keyword(row, hard_exclude_keywords):
            removed_items.append(row)
            continue
        if must_include_keywords and not matches_any_keyword(row, must_include_keywords):
            removed_items.append(row)
            continue
        safe_items.append(row)
        if matches_any_keyword(row, dislikes):
            dislike_items.append(row)

    return safe_items, removed_items, dislike_items


def _item_brief(item: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "item_id": item.get("item_id"),
        "name_th": item.get("name_th"),
        "name_en": item.get("name_en"),
        "category": item.get("category"),
        "price_baht": item.get("price_baht"),
        "allergens_verified": item.get("allergens_verified"),
        "score": item.get("score"),
    }


def _aggregate_by_item_id(selected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse repeats of the same dish into one entry with a quantity +
    subtotal, using `_item_brief`'s field set (tools.py-specific columns)."""
    return aggregate_by_item_id(selected, brief_fn=_item_brief)


_DRINK_CATEGORY = "เครื่องดื่ม"
_DESSERT_CATEGORY = "ของหวาน"


def _resolve_quantity_items(
    menu: List[Dict[str, Any]],
    category: str,
    selection_keywords: List[str],
    total_quantity: int,
) -> List[Dict[str, Any]]:
    """Resolve free-text choices (e.g. drink names) against one menu category,
    then split total_quantity as evenly as possible across however many
    distinct items were actually matched (e.g. 2 drink choices, 5 people ->
    3 + 2). Returns a flat list with repeats, same shape as dp_knapsack()'s
    output, so it aggregates and prices the same way as the DP-chosen food.

    Deliberately NOT scored/DP-optimized — drinks and dessert are picked by
    name, not competed for on value-for-money, since "1 drink per person" is
    a fixed requirement, not an optimization.
    """
    if not selection_keywords or total_quantity <= 0:
        return []

    category_items = [row for row in menu if row.get("category") == category]
    matched: List[Dict[str, Any]] = []
    seen_ids = set()
    for kw in selection_keywords:
        hit = next((row for row in category_items if matches_any_keyword(row, [kw])), None)
        if hit and hit["item_id"] not in seen_ids:
            matched.append(hit)
            seen_ids.add(hit["item_id"])

    if not matched:
        return []

    base_qty, remainder = divmod(total_quantity, len(matched))
    flat: List[Dict[str, Any]] = []
    for i, item in enumerate(matched):
        qty = base_qty + (1 if i < remainder else 0)
        flat.extend([item] * qty)
    return flat


# ----------------------------------------------------------------------
# Tool 1 — search_menu_items
# ----------------------------------------------------------------------
@tool
def search_menu_items(
    keyword: str = "",
    category: str = "",
    max_price: float = 100000,
) -> str:
    """ค้นหาเมนูซูชิ Sushiro ตามคำค้น (keyword), หมวดหมู่ (category) และ/หรือราคาสูงสุด (max_price).

    ใช้เมื่อผู้ใช้ถามหาเมนูเฉพาะเจาะจง เช่น "มีเมนูแซลมอนอะไรบ้าง" หรือ
    "ของทอดมีอะไรบ้าง". จับคู่แบบ substring (ไม่สนตัวพิมพ์เล็ก/ใหญ่) กับชื่อไทย,
    ชื่ออังกฤษ และ keywords ที่บันทึกไว้ในฐานข้อมูล โดยทนต่อการสะกดผิดเล็กน้อยได้
    (เช่น "เซลมอน" ยังหา "แซลมอน" เจอ). คืนค่าเป็น JSON string
    ของรายการเมนูที่พบ (สูงสุด 15 รายการ).
    """
    menu = menu_records()
    kw = keyword.strip().lower()
    cat = category.strip().lower()

    results = []
    for row in menu:
        if kw and not fuzzy_contains(matches_search_text(row), kw):
            continue
        if cat and cat not in str(row.get("category", "")).lower():
            continue
        if float(row.get("price_baht", 0)) > max_price:
            continue
        results.append(row)

    payload = {
        "count": len(results),
        "items": [_item_brief(r) for r in results[:15]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def matches_search_text(row: Dict[str, Any]) -> str:
    return " ".join(
        [
            str(row.get("name_th", "")),
            str(row.get("name_en", "")),
            str(row.get("keywords", "")),
        ]
    ).lower()


# ----------------------------------------------------------------------
# Tool 2 — filter_constraints
# ----------------------------------------------------------------------
@tool
def filter_constraints(
    allergens: Optional[List[str]] = None,
    dislikes: Optional[List[str]] = None,
) -> str:
    """กรองเมนูตามสารก่อภูมิแพ้ (allergens) และสิ่งที่ผู้ใช้ไม่ชอบ (dislikes).

    allergens ที่รู้จัก: fish, crustacean, molluscs, egg, milk, gluten, soy,
    sesame, pork — เมนูที่มีสารเหล่านี้ (จากคอลัมน์ allergens_verified เท่านั้น)
    จะถูกตัดออกโดยเด็ดขาด (hard block) ไม่ต้องอาศัยการเดาจากคำอธิบาย.
    dislikes เป็นคำสำคัญอิสระ (เช่น "หอย") ที่จะไม่ถูกตัดออก แต่คะแนนจะถูกหักภายหลัง.
    ใช้ก่อนขั้นตอน optimize เพื่อดูภาพรวมว่าเมนูใดถูกกรองออกไปบ้าง.
    """
    menu = menu_records()
    safe_items, blocked, dislike_items = _run_filter(menu, allergens, dislikes)

    payload = {
        "safe_count": len(safe_items),
        "blocked_count": len(blocked),
        "blocked_items": [_item_brief(r) for r in blocked],
        "dislike_flagged_count": len(dislike_items),
        "dislike_flagged_items": [_item_brief(r) for r in dislike_items[:10]],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# Tool 3 — build_optimal_set
# ----------------------------------------------------------------------
@tool
def build_optimal_set(
    budget: float,
    allergens: Optional[List[str]] = None,
    dislikes: Optional[List[str]] = None,
    preferred_keywords: Optional[List[str]] = None,
    hard_exclude_keywords: Optional[List[str]] = None,
    must_include_keywords: Optional[List[str]] = None,
    min_items: int = 1,
    max_items: int = 20,
    num_people: int = 1,
    drink_selection: Optional[List[str]] = None,
    drink_quantity: Optional[int] = None,
    drinks_separate_from_budget: bool = False,
    include_dessert: bool = False,
    dessert_selection: Optional[List[str]] = None,
    dessert_quantity: Optional[int] = None,
) -> str:
    """จัดชุดเมนูที่คุ้มค่าที่สุดภายในงบประมาณด้วย 0/1 Knapsack Dynamic Programming.

    พารามิเตอร์มี 4 ระดับ ห้ามใช้สลับกัน:
    - allergens: แพ้อาหารจริง (การแพทย์) — hard block, ตรวจจาก allergens_verified เท่านั้น
    - hard_exclude_keywords: ข้อจำกัดด้านอาหารที่ไม่ใช่การแพ้ แต่ต้อง "ตัดออกเด็ดขาด"
      เช่น "ไม่กินของดิบเลย", "ไม่แตะเนื้อหมู" — ใช้เมื่อผู้ใช้พูดชัดเจนว่าห้ามมีเลย
    - preferred_keywords: ชอบ/อยากได้ — แค่บวกคะแนน ไม่ตัดรายการอื่นออก
    - must_include_keywords: "กินแค่ X" / "เอาเฉพาะ X" — ตัดทุกอย่างที่ไม่ตรงออกทั้งหมด
      ต่างจาก preferred_keywords ตรงที่นี่คือข้อจำกัดเด็ดขาด ไม่ใช่แค่ให้คะแนนเพิ่ม

    เครื่องดื่มและของหวาน "ไม่ได้" ถูกจัดด้วย DP ร่วมกับอาหารหลัก — เป็นการจัดสรร
    แบบตายตัวต่างหาก: เครื่องดื่มเลือกจาก drink_selection (ชื่อเมนู — ต้องถามก่อน
    เสมอ ห้ามเดา) จำนวน drink_quantity แก้ว (ต้องถามจำนวนแยกต่างหากเสมอ ห้าม
    สมมติว่าเท่ากับ num_people เอง แม้จะเป็นค่าที่พบบ่อยก็ตาม) ส่วนของหวานเป็น
    "option" ที่จัดก็ต่อเมื่อ include_dessert=true (ต้องถามยืนยันก่อนเสมอว่ารับ
    ของหวานไหม) จำนวน dessert_quantity ชิ้น (ถามแยกเช่นเดียวกับเครื่องดื่ม) ถ้า
    ไม่ระบุ drink_quantity/dessert_quantity จะ fallback เป็น num_people
    ค่าใช้จ่ายของเครื่องดื่ม/ของหวาน ปกติจะถูกหักออกจาก budget ก่อน แล้วจึงนำงบ
    ที่เหลือไปจัด DP อาหารหลัก — เว้นแต่ drinks_separate_from_budget=true (ผู้ใช้
    ยืนยันว่าต้องการคิดแยกต่างหาก) ซึ่งจะให้ budget เต็มจำนวนไปกับอาหาร แล้วบวก
    ค่าเครื่องดื่ม/ของหวานเพิ่มเข้าไปต่างหาก (ยอดรวมสุดท้ายจะมากกว่า budget ที่ระบุ
    — ต้องบอกผู้ใช้ให้ชัดเจน)

    ขั้นตอนภายใน: (1) กรอง allergen/hard_exclude/must_include แบบ hard block,
    (2) ให้คะแนนแต่ละเมนูด้วย preference/price-efficiency/diversity แล้วหักคะแนน
    รายการที่ตรงกับ dislikes, (3) เลือกชุดที่คะแนนรวมสูงสุดภายในงบประมาณด้วย DP
    (คำตอบที่ดีที่สุดจริง ไม่ใช่ค่าประมาณ). เรียกใช้เมื่อมีงบประมาณครบถ้วนและพร้อม
    คำนวณ. หลังเรียก tool นี้ ต้องเรียก verify_result เสมอก่อนตอบผู้ใช้.

    ผลลัพธ์มีฟิลด์ count_by_must_include_keyword (คำนวณให้แล้ว ไม่ต้องนับเอง)
    เช่น {"กุ้ง": 3, "ปลา": 5} — ใช้ตอบคำถามแบบ "กินได้อย่างละกี่จาน" โดยตรง

    เมนูเดียวกันอาจถูกเลือกซ้ำได้สูงสุด 3 ครั้ง (เช่น 2 จานซูชิแซลมอน) เพื่อให้
    ยอดรวมใกล้เคียงงบประมาณที่สุด — แต่ละรายการใน selected มีฟิลด์ quantity
    (จำนวนจานของเมนูนั้น) และ subtotal_baht (ราคา x quantity) ให้ใช้ตรงๆ
    เช่น "ซูชิแซลมอน x2 - 80 บาท" ห้ามนับจำนวนจานเอง
    """
    menu = menu_records()

    # Drinks/dessert: a fixed allocation by name, reserved out of the budget
    # BEFORE the DP food search — never DP-optimized alongside the food.
    # Quantity is whatever was explicitly asked for; num_people is only a
    # fallback for callers that skip the quantity question entirely.
    resolved_drink_qty = drink_quantity if drink_quantity is not None else num_people
    resolved_dessert_qty = dessert_quantity if dessert_quantity is not None else num_people
    drink_items = _resolve_quantity_items(menu, _DRINK_CATEGORY, drink_selection or [], resolved_drink_qty)
    dessert_items = (
        _resolve_quantity_items(menu, _DESSERT_CATEGORY, dessert_selection or [], resolved_dessert_qty)
        if include_dessert
        else []
    )
    fixed_items = drink_items + dessert_items
    fixed_cost = round(sum(float(it["price_baht"]) for it in fixed_items), 2)
    food_budget = budget if drinks_separate_from_budget else max(0.0, budget - fixed_cost)
    food_max_items = max(1, max_items - len(fixed_items))

    food_menu = [row for row in menu if row.get("category") not in (_DRINK_CATEGORY, _DESSERT_CATEGORY)]
    safe_items, blocked, dislike_items = _run_filter(
        food_menu, allergens, dislikes, hard_exclude_keywords, must_include_keywords
    )
    dislike_ids = {row["item_id"] for row in dislike_items}

    scored_items = []
    for row in safe_items:
        item = dict(row)
        item["score"] = score_item(
            row,
            preferred_keywords=preferred_keywords,
            budget=food_budget,
            is_disliked=row["item_id"] in dislike_ids,
        )
        scored_items.append(item)

    food_selected = dp_knapsack(scored_items, food_budget, max_items=food_max_items)
    selected = food_selected + fixed_items
    food_total_price = round(sum(float(it["price_baht"]) for it in food_selected), 2)
    total_price = round(food_total_price + fixed_cost, 2)
    # When separate, the budget only measures the food portion (drinks/dessert
    # are billed on top); otherwise it measures everything together.
    budget_used_pct = (
        round(food_total_price / budget * 100, 1)
        if drinks_separate_from_budget
        else round(total_price / budget * 100, 1)
    ) if budget else 0.0

    # Computed here (not left for the LLM to count by eye) so a breakdown like
    # "กุ้ง 3 จาน, ปลา 5 จาน" is guaranteed accurate when the user asked for
    # counts per requested category (e.g. "กุ้งกับปลา กินได้อย่างละกี่จาน").
    count_by_must_include_keyword = (
        {kw: sum(1 for it in selected if matches_any_keyword(it, [kw])) for kw in must_include_keywords}
        if must_include_keywords
        else {}
    )

    result = {
        # Aggregated by dish (quantity + subtotal_baht) so repeats of the same
        # item — e.g. 2 plates of Salmon Sushi to land closer to the budget —
        # show as one line with "quantity": 2 instead of two duplicate rows.
        "selected": _aggregate_by_item_id(selected),
        "total_price": total_price,  # grand total actually paid (food + drinks + dessert)
        "food_total_price": food_total_price,
        "budget": budget,
        "budget_used_pct": budget_used_pct,
        "drinks_separate_from_budget": drinks_separate_from_budget,
        "item_count": len(selected),  # total plates, repeats counted individually
        "distinct_dish_count": len({it["item_id"] for it in selected}),
        "count_by_must_include_keyword": count_by_must_include_keyword,
        "min_items_requested": min_items,
        "max_items_requested": max_items,
        "categories": sorted({it.get("category", "") for it in selected}),
        "allergens_requested": sorted({str(a).strip().lower() for a in (allergens or [])}),
        "hard_exclude_keywords": list(hard_exclude_keywords or []),
        "must_include_keywords": list(must_include_keywords or []),
        "blocked_count": len(blocked),
        "meets_min_items": len(selected) >= min_items,
        "num_people": num_people,
        "drinks_cost": round(sum(float(it["price_baht"]) for it in drink_items), 2),
        "dessert_included": include_dessert,
        "dessert_cost": round(sum(float(it["price_baht"]) for it in dessert_items), 2),
    }

    set_last_result(result)

    return json.dumps(result, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# Tool 4 — verify_result
# ----------------------------------------------------------------------
@tool
def verify_result(
    budget: Optional[float] = None,
    allergens: Optional[List[str]] = None,
) -> str:
    """ตรวจสอบผลลัพธ์ล่าสุดจาก build_optimal_set (หรือ rag_augmented_build)
    ก่อนตอบผู้ใช้เสมอ ทุกครั้งไม่มีข้อยกเว้น.

    ตรวจ 5 เรื่อง: (1) ยอดรวมไม่เกินงบประมาณ, (2) ไม่มีเมนูที่มีสารก่อภูมิแพ้
    ที่ผู้ใช้แพ้หลุดเข้ามาในชุดที่เลือก, (3) มีอย่างน้อย 1 รายการถูกเลือก,
    (4) ไม่มีเมนูที่ตรงกับ hard_exclude_keywords หลุดเข้ามา, (5) ถ้ามีการระบุ
    must_include_keywords ทุกเมนูในชุดต้องตรงกับอย่างน้อยหนึ่งคำ.
    คืนค่า passed=true/false พร้อมรายการปัญหา (issues) หากพบ. ถ้า passed=false
    ต้องปรับพารามิเตอร์ (เช่น ลด min_items หรือเพิ่มงบ) แล้วเรียก
    build_optimal_set ใหม่ ห้ามส่งผลลัพธ์ที่ไม่ผ่านการตรวจสอบให้ผู้ใช้.
    """
    result = get_last_result()
    if result is None:
        return json.dumps(
            {"passed": False, "issues": ["ยังไม่มีผลลัพธ์จาก build_optimal_set ให้ตรวจสอบ"]},
            ensure_ascii=False,
        )

    issues: List[str] = []

    # When drinks/dessert are billed separately from the stated budget, the
    # budget only ever measured the food portion — checking the grand total
    # against it would flag an intentional, user-confirmed overage as a bug.
    price_to_check = (
        result.get("food_total_price", result["total_price"])
        if result.get("drinks_separate_from_budget")
        else result["total_price"]
    )
    check_budget = budget if budget is not None else result.get("budget")
    if check_budget is not None and price_to_check > float(check_budget) + 1e-6:
        issues.append(
            f"ยอดรวม {price_to_check} บาท เกินงบประมาณ {check_budget} บาท"
        )

    allergens_norm = {str(a).strip().lower() for a in (allergens or result.get("allergens_requested") or [])}
    if allergens_norm:
        for item in result["selected"]:
            item_allergens = parse_allergen_tags(item.get("allergens_verified"))
            leaked = allergens_norm & item_allergens
            if leaked:
                issues.append(
                    f"เมนู '{item.get('name_th')}' มีสารก่อภูมิแพ้ {sorted(leaked)} ที่ผู้ใช้แพ้ แต่หลุดเข้ามาในชุด"
                )

    if result["item_count"] < 1:
        issues.append("ไม่มีเมนูใดถูกเลือกเลย (งบอาจน้อยเกินไป หรือถูกกรองออกหมด)")

    hard_exclude = result.get("hard_exclude_keywords") or []
    if hard_exclude:
        for item in result["selected"]:
            if matches_any_keyword(item, hard_exclude):
                issues.append(
                    f"เมนู '{item.get('name_th')}' ตรงกับข้อห้าม {hard_exclude} แต่หลุดเข้ามาในชุด"
                )

    must_include = result.get("must_include_keywords") or []
    if must_include:
        for item in result["selected"]:
            if not matches_any_keyword(item, must_include):
                issues.append(
                    f"เมนู '{item.get('name_th')}' ไม่ตรงกับเงื่อนไข 'เอาเฉพาะ {must_include}' แต่ถูกเลือกมาด้วย"
                )

    payload = {"passed": len(issues) == 0, "issues": issues, "checked_result": result}
    return json.dumps(payload, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# Tool 5 — request_clarification
# ----------------------------------------------------------------------
_CLARIFICATION_QUESTIONS = {
    "budget": "งบประมาณที่ต้องการใช้ทั้งหมดกี่บาทครับ?",
    "allergens": "มีอาการแพ้อาหารชนิดใดบ้างไหมครับ (เช่น กุ้ง ปู ปลา ไข่ นม ถั่วเหลือง แป้งสาลี งา หมู)?",
    "allergy": "มีอะไรที่ไม่ชอบทาน หรือแพ้อาหารประเภทไหนไหมครับ?",
    "preferences": "มีเมนูหรือวัตถุดิบที่ชื่นชอบเป็นพิเศษไหมครับ?",
    "item_count": "ต้องการกี่จานโดยประมาณครับ?",
    "num_people": "รับประทานกันกี่คนครับ?",
    "drinks": "รับเครื่องดื่มอะไรบ้างครับ (เช่น ชาเขียวร้อน โค้ก มัทฉะลาเต้เย็น น้ำส้ม)?",
    "drink_quantity": "ต้องการเครื่องดื่มนี้กี่แก้วครับ?",
    "drinks_budget_mode": "ต้องการให้ค่าเครื่องดื่มรวมอยู่ในงบเดิม หรือคิดแยกต่างหากดีครับ?",
    "dessert": "รับของหวานด้วยไหมครับ?",
    "dessert_selection": "รับของหวานเมนูไหนดีครับ?",
    "dessert_quantity": "ต้องการของหวานนี้กี่ชิ้นครับ?",
}


@tool
def request_clarification(missing: List[str]) -> str:
    """สร้างคำถามกลับไปยังผู้ใช้ เมื่อข้อมูลที่จำเป็นยังไม่ครบหรือขัดแย้งกัน.

    ใช้เมื่อยังไม่มีงบประมาณ (budget) หรือข้อมูลสำคัญอื่นขาดหายไป ก่อนจะเรียก
    build_optimal_set ไม่ได้. รับรายการชื่อฟิลด์ที่ขาด เช่น ["budget"] แล้ว
    คืนค่าคำถามภาษาไทยที่เหมาะสมให้ Agent นำไปถามผู้ใช้ต่อ.
    """
    questions = [
        _CLARIFICATION_QUESTIONS.get(field, f"ขอข้อมูลเพิ่มเติมเกี่ยวกับ {field} หน่อยครับ")
        for field in missing
    ]
    return json.dumps({"missing": missing, "questions": questions}, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------
# Assemble the tool list handed to the ReAct Agent (agent.py)
# ----------------------------------------------------------------------
AGENT_TOOLS = [
    search_menu_items,
    filter_constraints,
    build_optimal_set,
    verify_result,
    request_clarification,
]

try:
    from .rag import RAG_TOOLS  # noqa: E402

    AGENT_TOOLS = AGENT_TOOLS + RAG_TOOLS
except ImportError:
    # FAISS / langchain-openai not installed — RAG tools are optional.
    pass
