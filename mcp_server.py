"""
mcp_server.py — Sushi-Budgeteer MCP Server

ให้บริการ Sushi-Budgeteer tools ผ่าน Model Context Protocol (MCP)
โดยใช้ FastMCP — MCP client ใดๆ เชื่อมต่อได้ทันที เช่น:
  - Claude Desktop
  - Cursor / Kiro
  - mcp_client_demo.py ที่มากับโปรเจกต์นี้

Transport modes:
  stdio (default) — สำหรับ desktop clients เช่น Claude Desktop
  sse             — สำหรับ web clients / HTTP (รัน: python mcp_server.py --sse)

Tools ที่ expose:
  1. search_menu          — ค้นหาเมนูด้วย keyword / category / ราคา
  2. filter_menu          — กรองเมนูตาม allergen (hard) และ dislike (soft)
  3. build_set            — จัดชุดเมนูด้วย DP Knapsack
  4. verify_set           — ตรวจสอบผลลัพธ์ก่อนส่งคำตอบ
  5. clarify              — สร้างคำถามเมื่อข้อมูลไม่ครบ
  6. semantic_search      — RAG semantic search ผ่าน FAISS
  7. rag_build_set        — RAG + DP จัดชุดเมนูจากคำอธิบายเชิงความหมาย

วิธีรัน:
  python mcp_server.py           # stdio mode (Claude Desktop)
  python mcp_server.py --sse     # SSE mode (HTTP on port 8000)
"""

from __future__ import annotations

import json
import os
import sys
import argparse
from typing import Any

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.join(ROOT, "sushi_budgeteer")
sys.path.insert(0, PKG)
sys.path.insert(0, ROOT)

# Load .env ถ้ามี
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# FastMCP setup
# ---------------------------------------------------------------------------
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    name="sushi-budgeteer",
    instructions=(
        "Sushi-Budgeteer จัดเซ็ตเมนูซูชิ Sushiro ตามงบประมาณและข้อจำกัดของผู้ใช้ "
        "ใช้ Dynamic Programming + RAG Semantic Search "
        "เพื่อหาชุดเมนูที่คุ้มค่าที่สุด โดยคำนึงถึง allergen และ preference"
    ),
)

# ---------------------------------------------------------------------------
# Import business logic (lazy — ไม่ crash ถ้า dependencies ยังไม่ครบ)
# ---------------------------------------------------------------------------
def _get_tools_module():
    from tools import _run_filter, _load_menu, _df_to_records
    return _run_filter, _load_menu, _df_to_records

def _get_optimizer():
    from optimizer import dp_knapsack, score_item, random_baseline, compare_dp_vs_random
    return dp_knapsack, score_item, random_baseline, compare_dp_vs_random

def _get_rag():
    from rag import semantic_search_menu, rag_augmented_build, get_vector_store
    return semantic_search_menu, rag_augmented_build, get_vector_store

# ---------------------------------------------------------------------------
# Helper: serialise result เป็น JSON string สำหรับ MCP response
# ---------------------------------------------------------------------------
def _to_json(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    except Exception:
        return str(obj)

# ===========================================================================
# Tool 1 — search_menu
# ===========================================================================

@mcp.tool()
def search_menu(
    keyword: str = "",
    category: str = "",
    max_price: int = 0,
    min_price: int = 0,
) -> str:
    """
    ค้นหาเมนูในฐานข้อมูล Sushiro

    Args:
        keyword:   คำค้นหา เช่น "แซลมอน", "salmon", "กุ้ง", "ปลาหมึก"
        category:  หมวดหมู่ เช่น "ปลาดิบ", "มากิ/โรล", "ของหวาน", "เครื่องดื่ม",
                   "ปรุงสุก", "ของทอด", "ซุป", "ไข่ปลา", "กุ้ง/ปู", "ชุดเซ็ต"
        max_price: ราคาสูงสุด (บาท) — 0 หมายถึงไม่จำกัด
        min_price: ราคาต่ำสุด (บาท) — 0 หมายถึงไม่จำกัด

    Returns:
        JSON string ของ {"items": [...], "count": int}
    """
    import pandas as pd
    _, _load_menu, _df_to_records = _get_tools_module()
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

    return _to_json({"items": _df_to_records(df), "count": len(df)})


# ===========================================================================
# Tool 2 — filter_menu
# ===========================================================================

@mcp.tool()
def filter_menu(
    allergens: list[str] | None = None,
    dislikes: list[str] | None = None,
    categories_wanted: list[str] | None = None,
) -> str:
    """
    กรองเมนูตามข้อจำกัดของผู้ใช้

    allergen (hard block) vs dislike (soft — ยังอยู่ใน pool แต่ score ต่ำ):
      - allergen tags: fish, crustacean, molluscs, egg, milk, gluten, soy, sesame, pork
      - dislikes: ชื่อ/keyword เช่น ["ปลาหมึก", "ของหวาน"]

    Args:
        allergens:         allergen tags ที่ต้องกรองออกอย่างเด็ดขาด
        dislikes:          keyword ที่ไม่ชอบ (soft filter)
        categories_wanted: กรองเฉพาะหมวดนี้ (None = ทุกหมวด)

    Returns:
        JSON string ของ {safe_items, allergen_blocked, dislike_items, counts}
    """
    _run_filter, _, _ = _get_tools_module()
    result = _run_filter(
        allergens=allergens or [],
        dislikes=dislikes or [],
        categories_wanted=categories_wanted,
    )
    return _to_json(result)


# ===========================================================================
# Tool 3 — build_set
# ===========================================================================

@mcp.tool()
def build_set(
    budget: int,
    preferred_keywords: list[str] | None = None,
    allergens: list[str] | None = None,
    dislikes: list[str] | None = None,
    min_items: int = 1,
    max_items: int = 20,
    require_categories: list[str] | None = None,
) -> str:
    """
    จัดชุดเมนูที่คุ้มค่าที่สุดภายในงบประมาณด้วย Dynamic Programming (0/1 Knapsack)

    Scoring (0–10 ต่อเมนู):
      - Preference match (0–5): ตรงกับ preferred_keywords
      - Price efficiency (0–3): ราคา 35–80 บาท ได้คะแนนเต็ม
      - Category diversity (0–2): หมวดที่หลากหลาย
      - Dislike penalty (-3): ถ้าตรง dislike ลดคะแนน

    Args:
        budget:             งบประมาณสูงสุด (บาท)
        preferred_keywords: keyword ที่ชอบ เช่น ["แซลมอน", "กุ้ง"]
        allergens:          allergen ที่ต้องห้าม — กรองออกก่อน DP
        dislikes:           keyword ที่ไม่ชอบ
        min_items:          จำนวนจานขั้นต่ำ
        max_items:          จำนวนจานสูงสุด
        require_categories: บังคับให้มีหมวดนี้

    Returns:
        JSON string ของ {selected_items, total_price, budget_utilization_pct,
                         total_score, item_count, categories_covered, feasible, message}
    """
    import pandas as pd
    _run_filter, _, _ = _get_tools_module()
    dp_knapsack, score_item, _, _ = _get_optimizer()

    allergens_clean = [a.lower().strip() for a in (allergens or [])]
    dislikes_clean  = [d.lower().strip() for d in (dislikes or [])]
    prefs_clean     = [k.lower() for k in (preferred_keywords or [])]

    filter_result = _run_filter(
        allergens=allergens_clean,
        dislikes=dislikes_clean,
        categories_wanted=require_categories,
    )

    safe_df    = pd.DataFrame(filter_result["safe_items"])
    dislike_df = pd.DataFrame(filter_result["dislike_items"])

    if safe_df.empty and dislike_df.empty:
        return _to_json({
            "selected_items": [], "total_price": 0, "budget": budget,
            "budget_utilization_pct": 0.0, "total_score": 0.0,
            "item_count": 0, "categories_covered": [],
            "feasible": False,
            "message": "ไม่มีเมนูที่ผ่านเงื่อนไข allergen",
        })

    if not safe_df.empty:
        safe_df = safe_df.copy(); safe_df["is_disliked"] = False
    if not dislike_df.empty:
        dislike_df = dislike_df.copy(); dislike_df["is_disliked"] = True

    all_df = pd.concat(
        [d for d in [safe_df, dislike_df] if not d.empty], ignore_index=True
    )

    items_scored = []
    for _, row in all_df.iterrows():
        s = score_item(
            row=row,
            preferred_keywords=prefs_clean,
            budget=budget,
            is_disliked=bool(row.get("is_disliked", False)),
        )
        items_scored.append({**row.to_dict(), "score": s})

    if not items_scored:
        return _to_json({
            "selected_items": [], "total_price": 0, "budget": budget,
            "budget_utilization_pct": 0.0, "total_score": 0.0,
            "item_count": 0, "categories_covered": [],
            "feasible": False, "message": "ไม่มีเมนูในระบบ",
        })

    min_price = min(i["price_baht"] for i in items_scored)
    if budget < min_price:
        return _to_json({
            "selected_items": [], "total_price": 0, "budget": budget,
            "budget_utilization_pct": 0.0, "total_score": 0.0,
            "item_count": 0, "categories_covered": [],
            "feasible": False,
            "message": f"งบ {budget} บาท น้อยกว่าเมนูที่ถูกสุด ({min_price} บาท)",
        })

    selected = dp_knapsack(items=items_scored, budget=budget, max_items=max_items)
    total_price = sum(i["price_baht"] for i in selected)
    utilization = round(total_price / budget * 100, 1) if budget > 0 else 0.0
    categories  = list({i["category"] for i in selected})
    total_score = round(sum(i["score"] for i in selected), 3)

    clean = [
        {k: v for k, v in i.items() if k not in ("score", "is_disliked", "allergen_set")}
        for i in selected
    ]

    feasible = len(selected) >= min_items
    msg = (
        f"จัดได้ {len(selected)} จาน รวม {total_price} บาท (ใช้งบ {utilization}%)"
        if feasible
        else f"จัดได้เพียง {len(selected)} จาน ต้องการขั้นต่ำ {min_items} จาน"
    )

    return _to_json({
        "selected_items": clean,
        "total_price": total_price,
        "budget": budget,
        "budget_utilization_pct": utilization,
        "total_score": total_score,
        "item_count": len(selected),
        "categories_covered": categories,
        "feasible": feasible,
        "message": msg,
    })


# ===========================================================================
# Tool 4 — verify_set
# ===========================================================================

@mcp.tool()
def verify_set(
    selected_items: list[dict],
    budget: int,
    allergens: list[str] | None = None,
) -> str:
    """
    ตรวจสอบผลลัพธ์ก่อนส่งให้ผู้ใช้

    ตรวจ 3 เรื่อง:
      1. ยอดรวมไม่เกินงบ
      2. ไม่มีเมนูที่มี allergen ต้องห้ามหลุดออก (ตรวจจาก allergens_verified ไม่ใช่ description)
      3. มีอย่างน้อย 1 รายการ

    Args:
        selected_items: รายการเมนูที่ถูกเลือก
        budget:         งบประมาณ (บาท)
        allergens:      allergen tags ที่ต้องห้าม

    Returns:
        JSON string ของ {passed, total_price, within_budget, allergen_violations, issues}
    """
    _, _load_menu, _ = _get_tools_module()
    allergens_clean = [a.lower().strip() for a in (allergens or [])]
    df = _load_menu()

    total_price   = sum(item.get("price_baht", 0) for item in selected_items)
    within_budget = total_price <= budget
    is_empty      = len(selected_items) == 0

    violations = []
    item_ids = [item.get("item_id") for item in selected_items if item.get("item_id")]
    if item_ids and allergens_clean:
        matched = df[df["item_id"].isin(item_ids)]
        for _, row in matched.iterrows():
            overlap = row["allergen_set"] & set(allergens_clean)
            if overlap:
                violations.append({
                    "item_id":        row["item_id"],
                    "name_th":        row["name_th"],
                    "allergens_found": list(overlap),
                })

    issues = []
    if is_empty:
        issues.append("ไม่มีเมนูในผลลัพธ์")
    if not within_budget:
        issues.append(f"ยอดรวม {total_price} บาท เกินงบ {budget} บาท")
    for v in violations:
        issues.append(f"เมนู '{v['name_th']}' มี allergen {v['allergens_found']}")

    return _to_json({
        "passed":              within_budget and not violations and not is_empty,
        "total_price":         total_price,
        "within_budget":       within_budget,
        "allergen_violations": violations,
        "is_empty":            is_empty,
        "issues":              issues,
    })


# ===========================================================================
# Tool 5 — clarify
# ===========================================================================

@mcp.tool()
def clarify(reason: str, missing_fields: list[str]) -> str:
    """
    สร้างข้อความถามผู้ใช้เมื่อข้อมูลไม่ครบหรือขัดแย้ง

    Args:
        reason:         เหตุผลที่ต้องถาม เช่น "ไม่มีงบประมาณ"
        missing_fields: field ที่ขาด เช่น ["budget", "allergens"]
                        field ที่รองรับ: budget, allergens, min_items, preferences

    Returns:
        JSON string ของ {clarification_needed, message, missing_fields}
    """
    field_prompts = {
        "budget":      "งบประมาณของคุณคือเท่าไหร่ (บาท)?",
        "allergens":   "คุณแพ้อาหารอะไรบ้าง? (เช่น ปลา กุ้ง ไข่ กลูเตน)",
        "min_items":   "ต้องการกี่จานขั้นต่ำ?",
        "preferences": "ชอบเมนูประเภทไหนเป็นพิเศษ?",
    }
    prompts = [field_prompts.get(f, f"กรุณาระบุ: {f}") for f in missing_fields]
    message = (
        f"ต้องการข้อมูลเพิ่มเติมเนื่องจาก: {reason}\n"
        + "\n".join(f"• {p}" for p in prompts)
    )
    return _to_json({
        "clarification_needed": True,
        "message":              message,
        "missing_fields":       missing_fields,
    })


# ===========================================================================
# Tool 6 — semantic_search  (RAG)
# ===========================================================================

@mcp.tool()
def semantic_search(
    query: str,
    top_k: int = 5,
    allergens_exclude: list[str] | None = None,
    max_price: int = 0,
) -> str:
    """
    ค้นหาเมนูด้วยความหมาย (Semantic Search) ผ่าน FAISS Vector Store

    ต่างจาก search_menu (substring) ตรงที่:
      - "อยากได้อะไรมันๆ ละลายในปาก" → ได้ otoro, uni, salmon belly
      - "ของหวานเบาๆ ไม่หวานมาก"      → ได้ sorbet, warabi mochi
      - "อาหารทอดกรอบกินเล่น"          → ได้ gyoza, karaage, tempura

    ต้อง build FAISS index ก่อน (ครั้งแรกเท่านั้น) ผ่าน get_rag_status

    Args:
        query:             คำอธิบายเชิงความหมาย
        top_k:             จำนวนผลลัพธ์ (default 5, max 10)
        allergens_exclude: allergen tags ที่ต้องกรองออก
        max_price:         ราคาสูงสุด (0 = ไม่จำกัด)

    Returns:
        JSON string ของ {results: [{item_id, name_th, similarity_score, ...}], count, method}
    """
    try:
        semantic_search_menu, _, _ = _get_rag()
    except ImportError as e:
        return _to_json({"error": f"RAG unavailable: {e}", "results": [], "count": 0})

    result = semantic_search_menu.invoke({
        "query":             query,
        "top_k":             min(top_k, 10),
        "allergens_exclude": allergens_exclude or [],
        "max_price":         max_price,
    })
    return _to_json(result)


# ===========================================================================
# Tool 7 — rag_build_set  (RAG + DP)
# ===========================================================================

@mcp.tool()
def rag_build_set(
    budget: int,
    preference_description: str,
    allergens: list[str] | None = None,
    dislikes: list[str] | None = None,
    min_items: int = 1,
    max_items: int = 20,
) -> str:
    """
    จัดชุดเมนูโดยใช้ RAG หา candidate pool ก่อน แล้วส่งเข้า DP Knapsack

    เหมาะกับ:
      - "อยากได้เมนูรสเข้มข้น มีทั้งปลาดิบและของทอด งบ 400 บาท"
      - "จัดเซ็ตสำหรับคนที่ชอบรสครีมมี่ งบ 350 บาท แพ้กุ้ง"

    Flow ภายใน:
      1. Embed preference_description → FAISS top-30
      2. Allergen hard filter
      3. score_item + similarity_bonus (similarity × 2.0)
      4. dp_knapsack(budget)
      5. Return result พร้อม retrieval_source

    Args:
        budget:                 งบประมาณ (บาท)
        preference_description: คำอธิบายความต้องการ (free text)
        allergens:              allergen tags ที่ต้องห้าม
        dislikes:               keyword ที่ไม่ชอบ
        min_items:              จำนวนจานขั้นต่ำ
        max_items:              จำนวนจานสูงสุด

    Returns:
        JSON string ของ {selected_items, total_price, retrieval_source,
                         retrieved_candidates, feasible, message, ...}
    """
    try:
        _, rag_augmented_build, _ = _get_rag()
    except ImportError as e:
        return _to_json({"error": f"RAG unavailable: {e}", "feasible": False})

    result = rag_augmented_build.invoke({
        "budget":                 budget,
        "preference_description": preference_description,
        "allergens":              allergens or [],
        "dislikes":               dislikes or [],
        "min_items":              min_items,
        "max_items":              max_items,
    })
    return _to_json(result)


# ===========================================================================
# Resource — menu_catalog  (MCP Resource: read-only data)
# ===========================================================================

@mcp.resource("sushiro://menu/catalog")
def menu_catalog() -> str:
    """
    รายการเมนูทั้งหมดในฐานข้อมูล Sushiro (read-only resource)

    MCP clients สามารถ read resource นี้เพื่อดูเมนูทั้งหมดได้โดยไม่ต้อง call tool
    """
    _, _load_menu, _df_to_records = _get_tools_module()
    df = _load_menu()
    items = _df_to_records(df)
    return _to_json({
        "total_items": len(items),
        "categories": sorted(df["category"].unique().tolist()),
        "price_range": {"min": int(df["price_baht"].min()), "max": int(df["price_baht"].max())},
        "allergen_tags": [
            "fish", "crustacean", "molluscs", "egg",
            "milk", "gluten", "soy", "sesame", "pork"
        ],
        "items": items,
        "disclaimer": (
            "⚠️ ข้อมูล allergen มาจาก dataset จำลองเท่านั้น "
            "ไม่รับประกันการปนเปื้อนจริงในร้าน"
        ),
    })


# ===========================================================================
# Resource — rag_status
# ===========================================================================

@mcp.resource("sushiro://rag/status")
def rag_status() -> str:
    """สถานะของ FAISS vector index"""
    index_path = os.path.join(PKG, "faiss_index")
    exists = os.path.exists(index_path)
    files  = os.listdir(index_path) if exists else []
    return _to_json({
        "index_exists":  exists,
        "index_path":    index_path,
        "index_files":   files,
        "status":        "ready" if exists else "not_built",
        "instructions":  (
            "call rebuild_index tool หรือกด Build Index ใน Streamlit UI "
            "เพื่อสร้าง vector index ก่อนใช้ semantic_search / rag_build_set"
            if not exists else "Vector index พร้อมใช้งาน"
        ),
    })


# ===========================================================================
# Tool — rebuild_index  (admin)
# ===========================================================================

@mcp.tool()
def rebuild_index() -> str:
    """
    สร้าง FAISS vector index ใหม่จาก menu CSV

    เรียกครั้งแรกก่อนใช้ semantic_search หรือ rag_build_set
    ใช้เวลาประมาณ 5–15 วินาที (embed 44 เมนูผ่าน OpenAI API)
    หลังจากนั้น index จะถูก save ไว้ใน disk ไม่ต้อง rebuild ซ้ำ

    Returns:
        JSON string ของ {success, message, index_path}
    """
    try:
        from rag import rebuild_index as _rebuild
        _rebuild()
        index_path = os.path.join(PKG, "faiss_index")
        return _to_json({
            "success":    True,
            "message":    "สร้าง FAISS index สำเร็จ พร้อมใช้งาน",
            "index_path": index_path,
        })
    except Exception as e:
        return _to_json({
            "success": False,
            "message": f"สร้าง index ไม่สำเร็จ: {e}",
        })


# ===========================================================================
# Prompt template — budget_optimizer
# ===========================================================================

@mcp.prompt()
def budget_optimizer(
    budget: int,
    allergens: str = "",
    preferences: str = "",
) -> str:
    """
    Prompt template สำหรับจัดเซ็ตเมนูซูชิตามงบประมาณ

    Args:
        budget:      งบประมาณ (บาท)
        allergens:   allergen ที่แพ้ คั่นด้วย comma เช่น "fish,gluten"
        preferences: สิ่งที่ชอบ เช่น "แซลมอน,กุ้ง"
    """
    allergen_list = [a.strip() for a in allergens.split(",") if a.strip()]
    pref_list     = [p.strip() for p in preferences.split(",") if p.strip()]

    parts = [f"ช่วยจัดเซ็ตเมนูซูชิสำหรับงบ {budget} บาท"]
    if allergen_list:
        parts.append(f"แพ้: {', '.join(allergen_list)}")
    if pref_list:
        parts.append(f"ชอบ: {', '.join(pref_list)}")
    parts.append("โดยใช้ build_set tool แล้วตาม verify_set ก่อนตอบ")

    return "\n".join(parts)


# ===========================================================================
# Entrypoint
# ===========================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sushi-Budgeteer MCP Server")
    parser.add_argument(
        "--sse",
        action="store_true",
        help="Run in SSE mode (HTTP) instead of stdio",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for SSE mode (default: 8000)",
    )
    args = parser.parse_args()

    if args.sse:
        print(f"[MCP] Starting SSE server on http://localhost:{args.port}/sse", flush=True)
        mcp.run(transport="sse")
    else:
        # stdio — default สำหรับ Claude Desktop / Kiro
        mcp.run(transport="stdio")
