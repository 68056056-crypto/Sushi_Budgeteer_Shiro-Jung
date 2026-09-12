"""MCP (Model Context Protocol) server exposing Shiro-Jung's tools.

This lets external AI assistants (Claude Desktop, Cursor, ...) call the same
search/filter/optimize/verify/clarify logic used by the Streamlit app,
through the open MCP standard, without importing any of this project's
Python code directly.

Usage:
    python mcp_server.py            # stdio transport (default, for Claude Desktop)
    python mcp_server.py --sse      # SSE/HTTP transport on port 8000

Every MCP tool here is a thin wrapper around the exact same LangChain tool
objects used by the ReAct agent (sushi_budgeteer.tools / sushi_budgeteer.rag)
— there is only one implementation of the actual logic.
"""

from __future__ import annotations

import argparse
import json
from typing import List, Optional

from mcp.server.fastmcp import FastMCP

from sushi_budgeteer.optimizer import menu_records
from sushi_budgeteer.tools import (
    build_optimal_set,
    filter_constraints,
    request_clarification,
    search_menu_items,
    verify_result,
)

mcp = FastMCP("Shiro-Jung")


@mcp.tool()
def search_menu(keyword: str = "", category: str = "", max_price: float = 100000) -> str:
    """ค้นหาเมนูซูชิ Sushiro ตามคำค้น (keyword), หมวดหมู่ (category) และ/หรือราคาสูงสุด."""
    return search_menu_items.invoke({"keyword": keyword, "category": category, "max_price": max_price})


@mcp.tool()
def filter_menu(allergens: Optional[List[str]] = None, dislikes: Optional[List[str]] = None) -> str:
    """กรองเมนูตามสารก่อภูมิแพ้ (hard block) และสิ่งที่ผู้ใช้ไม่ชอบ (soft penalty)."""
    return filter_constraints.invoke({"allergens": allergens or [], "dislikes": dislikes or []})


@mcp.tool()
def build_set(
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

    hard_exclude_keywords = ตัดออกเด็ดขาด (ข้อจำกัดอาหารที่ไม่ใช่ allergen เช่น "ของดิบ").
    must_include_keywords = "เอาเฉพาะ" รายการที่ตรงเท่านั้น เช่น ["กุ้ง", "ปลา"].
    เครื่องดื่ม (drink_selection) จัดสรรจำนวน drink_quantity แก้ว (ถามแยกจากชื่อเมนู
    เสมอ ไม่ fallback เป็น num_people โดยอัตโนมัติเว้นแต่ไม่ระบุ); ของหวานเป็น
    option ที่จัดก็ต่อเมื่อ include_dessert=true เท่านั้น (จำนวน dessert_quantity
    ชิ้น). drinks_separate_from_budget=true ให้อาหารใช้งบเต็มจำนวน แล้วบวกค่า
    เครื่องดื่ม/ของหวานเพิ่มต่างหาก.
    """
    return build_optimal_set.invoke(
        {
            "budget": budget,
            "allergens": allergens or [],
            "dislikes": dislikes or [],
            "preferred_keywords": preferred_keywords or [],
            "hard_exclude_keywords": hard_exclude_keywords or [],
            "must_include_keywords": must_include_keywords or [],
            "min_items": min_items,
            "max_items": max_items,
            "num_people": num_people,
            "drink_selection": drink_selection or [],
            "drink_quantity": drink_quantity,
            "drinks_separate_from_budget": drinks_separate_from_budget,
            "include_dessert": include_dessert,
            "dessert_selection": dessert_selection or [],
            "dessert_quantity": dessert_quantity,
        }
    )


@mcp.tool()
def verify_set(budget: Optional[float] = None, allergens: Optional[List[str]] = None) -> str:
    """ตรวจสอบผลลัพธ์ล่าสุดจาก build_set/rag_build_set ก่อนนำไปใช้จริงเสมอ.

    ตรวจ allergen, hard_exclude_keywords, และ must_include_keywords ทั้งหมด
    (สองอย่างหลังอ่านจากผลลัพธ์ล่าสุดโดยอัตโนมัติ ไม่ต้องส่งซ้ำ).
    """
    return verify_result.invoke({"budget": budget, "allergens": allergens or []})


@mcp.tool()
def clarify(missing: List[str]) -> str:
    """สร้างคำถามกลับไปยังผู้ใช้เมื่อข้อมูลที่จำเป็น (เช่น budget) ยังขาดหายไป."""
    return request_clarification.invoke({"missing": missing})


try:
    from sushi_budgeteer.rag import rag_augmented_build_tool, semantic_search_menu_tool

    @mcp.tool()
    def semantic_search(query: str, k: int = 5, allergens: Optional[List[str]] = None) -> str:
        """ค้นหาเมนูเชิงความหมาย (RAG) ด้วย FAISS Vector Store แทนการจับคู่ substring."""
        return semantic_search_menu_tool.invoke({"query": query, "k": k, "allergens": allergens or []})

    @mcp.tool()
    def rag_build_set(
        query: str,
        budget: float,
        allergens: Optional[List[str]] = None,
        dislikes: Optional[List[str]] = None,
        preferred_keywords: Optional[List[str]] = None,
        hard_exclude_keywords: Optional[List[str]] = None,
        must_include_keywords: Optional[List[str]] = None,
    ) -> str:
        """จัดชุดเมนูที่คุ้มค่าที่สุด โดยเริ่มจากการค้นหาเชิงความหมาย (RAG) ก่อนคำนวณด้วย DP."""
        return rag_augmented_build_tool.invoke(
            {
                "query": query,
                "budget": budget,
                "allergens": allergens or [],
                "dislikes": dislikes or [],
                "preferred_keywords": preferred_keywords or [],
                "hard_exclude_keywords": hard_exclude_keywords or [],
                "must_include_keywords": must_include_keywords or [],
            }
        )

    _RAG_ENABLED = True
except ImportError:
    _RAG_ENABLED = False


@mcp.resource("sushiro://menu/catalog")
def menu_catalog() -> str:
    """แคตตาล็อกเมนูทั้งหมดของ Sushiro (JSON) — ทุกคอลัมน์รวมถึง allergens_verified."""
    return json.dumps(menu_records(), ensure_ascii=False, indent=2)


@mcp.prompt()
def budget_optimizer(budget: str, allergens: str = "", preferences: str = "") -> str:
    """คำสั่งสำเร็จรูปสำหรับขอให้ Agent จัดชุดเมนูซูชิตามงบประมาณ/อาการแพ้/ความชอบ."""
    parts = [f"จัดเซ็ตเมนูซูชิ Sushiro ให้คุ้มค่าที่สุดภายในงบ {budget} บาท"]
    if allergens:
        parts.append(f"แพ้: {allergens}")
    if preferences:
        parts.append(f"ชอบ: {preferences}")
    return " ".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Shiro-Jung MCP Server")
    parser.add_argument(
        "--sse", action="store_true", help="Run over SSE/HTTP on port 8000 instead of stdio"
    )
    args = parser.parse_args()

    if args.sse:
        mcp.settings.port = 8000
        mcp.run(transport="sse")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
