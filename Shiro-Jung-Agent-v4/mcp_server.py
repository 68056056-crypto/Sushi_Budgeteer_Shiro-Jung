"""SQLite-backed MCP server. One stdio subprocess per client/session."""
from __future__ import annotations
import json
from typing import Dict, List, Optional
from mcp.server.fastmcp import FastMCP
from sushi_budgeteer.database import records, status
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.tools import search_menu_items, filter_constraints, request_clarification

mcp=FastMCP("Shiro-Jung-SQLite")
service=MenuService()

def encode(value):
    return json.dumps(value,ensure_ascii=False,indent=2)

@mcp.tool()
def search_menu(keyword: str = "", category: str = "", max_price: float = 100000) -> str:
    """ค้นชื่อเมนู/หมวด/ราคา จากฐานข้อมูล SQLite จริง ไม่ใช่ข้อมูลจากความจำ LLM."""
    return search_menu_items.invoke(locals())

@mcp.tool()
def get_menu_item(item_id: str) -> str:
    """ดึงรายละเอียด ราคา แหล่งข้อมูลและสถานะ allergen ของ item_id จาก SQLite."""
    item=next((r for r in records() if r['item_id']==item_id),None)
    return encode({'found':item is not None,'item':item})

@mcp.tool()
def database_status() -> str:
    """ตรวจจำนวนเมนู revision และจำนวนข้อมูลราคา/allergen ที่ยังไม่ยืนยัน."""
    return encode(status())

@mcp.tool()
def filter_menu(allergens: Optional[List[str]] = None, dislikes: Optional[List[str]] = None) -> str:
    """แสดงผลการกรอง allergen (hard) และ dislikes (soft) จากฐานข้อมูลจริง."""
    return filter_constraints.invoke(locals())

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
    drink_quantities: Optional[Dict[str, int]] = None,
    spend_ratio: float = 1.0,
) -> str:
    """สร้าง candidate ด้วย bounded exact DP จาก SQLite หลังกรอง hard constraints.

    จำนวน min/max นับทุกรายการรวมอาหาร เครื่องดื่ม ของหวาน แต่ต้องมีอาหารอย่างน้อยหนึ่งจาน.
    ถ้าขัดเงื่อนไขคืน requires_clarification ห้ามแนะนำผลนั้นหรือเปลี่ยนงบ/allergen เอง.
    ถ้า status=candidate ต้องเรียก verify_set ด้วย result_id ก่อนตอบ.
    """
    return encode(service.build(**locals()))

@mcp.tool()
def alternative_set(result_id: str) -> str:
    """Internal second option: retain all constraints and diversify food only."""
    return encode(service.alternative(result_id))

@mcp.tool()
def verify_set(result_id: str) -> str:
    """ตรวจ candidate ที่ server เก็บด้วย result_id; คำนวณยอดใหม่จาก SQLite.

    ต้องผ่านก่อนนำรายการไปตอบผู้ใช้ ถ้าฐานข้อมูลเปลี่ยนหรือไม่ผ่านให้จัดใหม่/ถามเพิ่ม.
    """
    return encode(service.verify(result_id))

@mcp.tool()
def clarify(missing: List[str]) -> str:
    """สร้างคำถามข้อมูลที่ขาด เช่น budget/num_people/allergy/drinks/dessert."""
    return request_clarification.invoke(locals())

@mcp.resource("sushiro://menu/catalog")
def menu_catalog() -> str:
    """เมนูจาก SQLite รวม provenance รายรายการ."""
    return encode(records())

@mcp.resource("sushiro://menu/status")
def menu_status() -> str:
    """สถานะฐานข้อมูลและ revision สำหรับ audit."""
    return encode(status())

@mcp.prompt()
def budget_optimizer(budget: str, allergens: str = "", preferences: str = "") -> str:
    """เป้าหมายตัวอย่างสำหรับ Agent; ต้อง search/build/verify ตามสถานการณ์."""
    return f"จัดชุดงบ {budget} บาท allergen={allergens} ชอบ={preferences}; ใช้ฐานข้อมูลและ verify ก่อนตอบ"

def main():
    # Intentionally stdio only: no unauthenticated shared network server.
    mcp.run(transport="stdio")

if __name__=='__main__': main()
