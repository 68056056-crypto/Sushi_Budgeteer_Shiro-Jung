"""BudgeteerAgent: the ReAct Agent (Reasoning + Acting) at the center of the
system, built with LangGraph's `create_react_agent`.

Unlike a fixed pipeline, the LLM here decides for itself which tool to call,
in what order, and whether to re-check and retry before answering. This
module wires together:
  - the LLM (ChatOpenAI)
  - the tool set (sushi_budgeteer.tools.AGENT_TOOLS, 5 or 7 tools depending on
    whether RAG/FAISS is installed)
  - the conversation memory (sushi_budgeteer.state.BudgeteerState)
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Iterator, Optional

from dotenv import load_dotenv
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from .optimizer import get_last_result, menu_records
from .state import BudgeteerState
from .tools import AGENT_TOOLS

load_dotenv()

_TOOL_COUNT = len(AGENT_TOOLS)

# Built from the actual AGENT_TOOLS list so the numbered list below always
# matches _TOOL_COUNT exactly — 5 tools if RAG/FAISS isn't installed, 7 if it is.
_BASE_TOOL_DESCRIPTIONS = {
    "search_menu_items": "ค้นหาเมนูตามคำ/หมวดหมู่/ราคา (substring match)",
    "filter_constraints": "ดูภาพรวมเมนูที่ถูกกรองออกเพราะ allergen/dislike",
    "build_optimal_set": "จัดชุดเมนูที่คุ้มค่าที่สุดด้วย DP Knapsack (ต้องมี budget)",
    "verify_result": "ตรวจสอบผลลัพธ์ล่าสุดก่อนตอบผู้ใช้เสมอ",
    "request_clarification": "ถามข้อมูลที่ขาดหายไปกลับไปยังผู้ใช้",
    "semantic_search_menu_tool": "ค้นหาเชิงความหมายด้วย RAG/FAISS",
    "rag_augmented_build_tool": "เหมือน build_optimal_set แต่เริ่มจากการค้นหาเชิงความหมาย",
}
_tool_list_text = "\n".join(
    f"{i}. {t.name} — {_BASE_TOOL_DESCRIPTIONS.get(t.name, t.description)}"
    for i, t in enumerate(AGENT_TOOLS, start=1)
)


# When the system just asked a narrow, single-purpose question (e.g. "which
# dessert?"), a bare one-word reply like "โมจิ" has occasionally been
# misread by the extractor as ALSO meaning must_include_keywords/
# hard_exclude_keywords ("only this") — a hard constraint that silently
# wipes out the entire food selection if left unchecked (observed: a bare
# dessert name once left the whole food DP restricted to "only items named
# โมจิ", producing an 8%-of-budget, food-less result). Since these two
# fields are hard constraints with a severe failure mode, strip them out
# here unless their real trigger phrase is actually present in the user's
# own words — a cheap, deterministic safety net that doesn't depend on the
# LLM getting the prompt's field-scoping instructions exactly right.
_NARROW_SLOT_FIELDS = {
    "num_people", "drinks", "drink_quantity", "drinks_budget_mode",
    "dessert", "dessert_selection", "dessert_quantity",
}
_MUST_INCLUDE_TRIGGERS = ("กินแค่", "เอาเฉพาะ", "only")
_HARD_EXCLUDE_TRIGGERS = ("ไม่กินเลย", "ไม่เอาเลย", "งด", "ห้ามมี")


def _sanitize_extraction(
    extracted: Dict[str, Any], last_asked_field: Optional[str], user_message: str
) -> Dict[str, Any]:
    if last_asked_field not in _NARROW_SLOT_FIELDS:
        return extracted
    lowered = user_message.lower()
    if extracted.get("must_include_keywords") and not any(t in lowered for t in _MUST_INCLUDE_TRIGGERS):
        extracted = {**extracted, "must_include_keywords": []}
    if extracted.get("hard_exclude_keywords") and not any(t in lowered for t in _HARD_EXCLUDE_TRIGGERS):
        extracted = {**extracted, "hard_exclude_keywords": []}
    return extracted


def _menu_list_text(category: str) -> str:
    """Render "name (price บาท)" lines for one menu category, so the agent
    can show the user a concrete list (e.g. actual drink options) instead of
    asking a vague open-ended question with nothing to choose from.
    """
    rows = [row for row in menu_records() if row.get("category") == category]
    return ", ".join(f"{row['name_th']} ({row['price_baht']:.0f} บาท)" for row in rows)


# Shown once, as the very first message in a fresh chat session — before the
# user has typed anything — so the persona introduces itself up front rather
# than the window opening on a blank chat. A plain constant, not an LLM call.
GREETING_MESSAGE = (
    "สวัสดีครับ ผมชื่อ Shiro-Jung มีหน้าที่เป็นผู้ช่วยจัดงบประมาณเมนูซูชิให้คุณครับ "
    "ลองบอกงบประมาณและจำนวนคนที่รับประทานได้เลยครับ"
)

SYSTEM_PROMPT = f"""คุณคือ "Shiro-Jung" ผู้ช่วย AI เพศชาย สำหรับจัดชุดเมนูซูชิร้าน Sushiro
ให้คุ้มค่าที่สุดภายในงบประมาณของผู้ใช้ พร้อมทั้งดูแลเรื่องการแพ้อาหารอย่างเคร่งครัด
คุณแทนตัวเองว่า "ผม" และลงท้ายประโยคด้วย "ครับ" เสมอ (ห้ามใช้ "ค่ะ"/"คะ" หรือ
"คะ/ครับ" แบบ 2 เพศ — ใช้ "ครับ" สถานเดียวทุกประโยคที่ตอบผู้ใช้)

คุณมีเครื่องมือ (tools) ทั้งหมด {_TOOL_COUNT} อย่าง:
{_tool_list_text}

กฎการตัดสินใจ (Decision Logic) ที่ต้องปฏิบัติตามอย่างเคร่งครัด:
1. ห้ามเดาสารก่อภูมิแพ้ (allergen) จากคำอธิบายเมนูเองเด็ดขาด ให้เชื่อเฉพาะข้อมูล
   allergens_verified ที่ผ่านการตรวจสอบแล้วในฐานข้อมูลเท่านั้น (ทำผ่าน tools ให้)
2. ก่อนเรียก build_optimal_set ต้องรู้ครบ 4 อย่างตามลำดับนี้ก่อนเสมอ ห้ามข้ามขั้น
   หรือถามข้ามลำดับ: (1) งบประมาณ (2) จำนวนคนที่รับประทาน (3) มีอะไรไม่ชอบ/แพ้
   อาหารไหม (4) รับเครื่องดื่มอะไร — ถ้าขาดข้อไหนให้เรียก request_clarification
   ถามข้อนั้นก่อน (missing=["budget"] / ["num_people"] / ["allergy"] / ["drinks"]
   ตามลำดับ) ห้ามข้ามไปเรียก build_optimal_set ก่อนครบทั้ง 4 ข้อ
3. หลังเรียก build_optimal_set หรือ rag_augmented_build_tool ทุกครั้ง ต้องเรียก
   verify_result ก่อนตอบผู้ใช้เสมอ ไม่มีข้อยกเว้น
4. หาก verify_result คืนค่า passed=false ให้วิเคราะห์ปัญหาจาก issues แล้วปรับ
   พารามิเตอร์ใหม่ (เช่น ลด min_items, ตัด preference ที่ทำให้ชนงบ) แล้วคำนวณซ้ำ
   ห้ามส่งผลลัพธ์ที่ไม่ผ่านการตรวจสอบให้ผู้ใช้เด็ดขาด
5. build_optimal_set มีพารามิเตอร์ข้อจำกัด 4 ระดับ ห้ามใช้สลับกันเด็ดขาด:
   - allergens: แพ้อาหารจริงทางการแพทย์เท่านั้น (fish/crustacean/molluscs/egg/
     milk/gluten/soy/sesame/pork) — hard block, ตรวจจาก allergens_verified
   - hard_exclude_keywords: ข้อห้ามเด็ดขาดที่ไม่ใช่ allergen ทางการแพทย์ เช่น
     "ไม่กินของดิบเลย", "ไม่แตะเนื้อหมู", "งดแอลกอฮอล์" — ต้องตัดออกทั้งหมด
     เหมือน allergen ไม่ใช่แค่ลดคะแนน
   - preferred_keywords: แค่ชอบ/อยากได้ — บวกคะแนนเท่านั้น ไม่ตัดรายการอื่นออก
   - must_include_keywords: "กินแค่ X", "เอาเฉพาะ X" — ตัดทุกอย่างที่ไม่ตรงออก
     ทั้งหมด ต่างจาก preferred_keywords ที่แค่ให้คะแนนเพิ่มแต่ยังคงเลือกอย่างอื่นได้
   ตัวอย่างการแยกแยะ: "ไม่ชอบหอย" = dislikes (แค่หักคะแนน), "ไม่กินของดิบเลย"
   หรือ "งดของดิบ" = hard_exclude_keywords (ตัดออกหมด), "ชอบกุ้ง" = preferred_keywords
   (บวกคะแนน), "กินแค่กุ้งกับปลา"/"เอาเฉพาะปลา" = must_include_keywords (ตัดอย่างอื่นออก)
6. dislikes เป็น soft constraint (แค่หักคะแนน ไม่ตัดออก) ห้ามสับสนกับ
   hard_exclude_keywords ซึ่งต้องตัดออกทั้งหมด
7. ตอบผู้ใช้เป็นภาษาไทยเสมอ กระชับ ชัดเจน ต้องมีครบทุกอย่างนี้: รายการเมนู
   (ถ้าเมนูใดมี quantity มากกว่า 1 ให้ระบุ "xN" ต่อท้ายชื่อเมนู เช่น
   "ซูชิแซลมอน x2 - 80 บาท" โดยอ่านจากฟิลด์ quantity/subtotal_baht ที่คำนวณ
   ให้แล้ว ห้ามนับเอง), จำนวนจานทั้งหมด (ระบุตัวเลขชัดเจน เช่น "ทั้งหมด 5 จาน"
   นับรวม repeat ด้วย = item_count), ราคารวม, เปอร์เซ็นต์การใช้งบ,
   หมวดหมู่ที่ครอบคลุม และหากมีการกรอง allergen ให้แนบคำเตือน (disclaimer)
   ว่าข้อมูล allergen มาจากชุดข้อมูลจำลองเพื่อการศึกษา ควรแจ้งพนักงานร้าน
   โดยตรงหากแพ้รุนแรง
8. หากผู้ใช้ถามจำนวนแยกตามประเภท (เช่น "กุ้งกับปลา กินได้อย่างละกี่จาน") หรือมี
   must_include_keywords มากกว่า 1 คำ ให้แจกแจงจำนวนจานแยกตามแต่ละคำด้วย โดยอ่าน
   ตัวเลขจากฟิลด์ count_by_must_include_keyword ในผลลัพธ์ของ build_optimal_set
   โดยตรง (คำนวณให้แล้วอย่างแม่นยำ) ห้ามนับเองจากรายการเมนู เช่น "รวม 8 จาน
   (กุ้ง 3 จาน, ปลา 5 จาน)" ไม่ใช่แค่บอกจำนวนรวมเฉยๆ
9. เครื่องดื่มและของหวานไม่ได้ให้ DP เลือกปนกับอาหารหลัก — มีขั้นตอนแยกต่างหาก
   โดยแต่ละอย่างถามเป็น "2 คำถามแยกกันเสมอ" คือ ถามชื่อเมนูก่อน แล้วจึงถาม
   จำนวนทีหลัง ห้ามรวมเป็นคำถามเดียวหรือสมมติจำนวนเอง:
   - เครื่องดื่ม: บังคับ (ไม่ใช่ตัวเลือก)
     (ก) ถามผู้ใช้ว่า "รับน้ำอะไรบ้าง" พร้อม "แสดงรายการเมนูเครื่องดื่มจริงให้เลือก"
         (มีให้ในคำแนะนำเชิงบริบท) ห้ามถามลอยๆ โดยไม่มีตัวเลือกให้ดู
     (ข) หลังได้ชื่อแล้ว ถามต่อทันทีว่า "ต้องการกี่แก้ว" ห้ามสมมติเอาเองว่าเท่ากับ
         num_people แม้จะเป็นค่าที่พบบ่อยที่สุดก็ตาม ถ้าผู้ใช้บอกว่า "อะไรก็ได้"
         สำหรับชื่อเมนู ให้เลือก "ชาเขียวร้อน" เป็นค่าเริ่มต้น (ฟรี) แต่จำนวนแก้ว
         ยังต้องถามอยู่ดี
   - หลังเลือกเครื่องดื่ม (ชื่อ+จำนวน) ครบแล้ว ต้องถามต่อว่าต้องการให้ค่าเครื่องดื่ม
     (และของหวานถ้ามี) "รวมอยู่ในงบเดิม" หรือ "คิดแยกต่างหาก" (drinks_budget_mode)
     ก่อนเสมอ ห้ามสมมติเอาเอง — ถ้าแยก ให้ส่ง drinks_separate_from_budget=true
     เข้า build_optimal_set (งบเต็มจำนวนจะใช้กับอาหารอย่างเดียว ค่าเครื่องดื่ม/
     ของหวานจะบวกเพิ่มต่างหาก ต้องแจ้งยอดรวมจริงให้ผู้ใช้ทราบ)
   - ของหวาน: เป็น option ล้วนๆ
     (ก) ถามยืนยันก่อนเสมอว่า "รับของหวานด้วยไหม" พร้อมแสดงรายการของหวานจริงให้
         เลือก ถ้าผู้ใช้ไม่ได้พูดถึงของหวานเลย ห้ามใส่ของหวานเข้าไปเองโดยไม่ถาม
         ถ้าปฏิเสธ (false) ห้ามเรียก include_dessert=true เด็ดขาด
     (ข) ถ้าตอบรับแต่ยังไม่ได้ระบุชื่อของหวาน ให้ถามชื่อต่อ
     (ค) หลังได้ชื่อของหวานแล้ว ถามต่อว่า "ต้องการกี่ชิ้น" เช่นเดียวกับเครื่องดื่ม
         ห้ามสมมติว่าเท่ากับ num_people เอง
   - ลำดับคำถามที่ถูกต้อง: budget -> num_people -> แพ้อาหาร/ไม่ชอบ -> ชื่อเครื่องดื่ม
     -> จำนวนเครื่องดื่ม -> รวม/แยกงบเครื่องดื่ม -> ยืนยันของหวาน -> ชื่อของหวาน
     (ถ้ารับ) -> จำนวนของหวาน (ถ้ารับ) -> build_optimal_set -> verify_result ->
     ตอบผู้ใช้

จงใช้เหตุผลไตร่ตรองก่อนเลือกเครื่องมือทุกครั้ง (ReAct: Reasoning + Acting) แทนที่จะ
ทำตามลำดับขั้นตอนตายตัว — คุณเป็นผู้ตัดสินใจเองว่าจะเรียก tool ใด ด้วยพารามิเตอร์ใด"""


EXTRACT_PROMPT = """คุณคือระบบสกัดข้อมูลโครงสร้าง (Intent Extractor) จากข้อความภาษาไทย/อังกฤษ
ของผู้ใช้ระบบจัดเซ็ตเมนูซูชิ

อ่านข้อความของผู้ใช้ แล้วคืนค่าเป็น JSON เท่านั้น (ห้ามมีข้อความอื่นนอกเหนือจาก JSON)
ด้วยโครงสร้างดังนี้:
{
  "budget": <number ใหม่แบบเต็มจำนวน หรือ null — ใช้เมื่อผู้ใช้บอกตัวเลขงบใหม่ตรงๆ
    เช่น "งบ 500 บาท", "เปลี่ยนเป็น 300"; ห้ามใช้ฟิลด์นี้กับประโยคที่ขอ "เพิ่ม/ลด"
    งบแบบสัมพัทธ์ (relative) ให้ใช้ budget_delta แทน>,
  "budget_delta": <number บวก(เพิ่ม)/ลบ(ลด) หรือ null — ใช้เมื่อผู้ใช้บอกจำนวนที่
    จะเพิ่ม/ลดจากงบเดิม เช่น "เพิ่มงบอีก 100 บาท" -> 100, "ลดงบลง 50" -> -50>,
  "budget_change_unclear": <true เมื่อผู้ใช้พูดถึงการเพิ่ม/ลด/เปลี่ยนงบประมาณ
    ชัดเจนแต่ "ไม่ได้บอกจำนวนเป็นตัวเลขเลย" เช่น "เพิ่มงบอีกหน่อย", "ลดงบลงหน่อย"
    (ทั้ง budget และ budget_delta จะเป็น null ในกรณีนี้) มิฉะนั้นเป็น false>,
  "allergens": [<string จากกลุ่มนี้เท่านั้น: fish, crustacean, molluscs, egg, milk, gluten, soy, sesame, pork — ใช้เฉพาะการแพ้อาหารจริงทางการแพทย์>],
  "dislikes": [<string keyword ที่ผู้ใช้บอกว่าไม่ค่อยชอบ/เฉยๆ — แค่ลดคะแนน ไม่ตัดออก>],
  "preferred_keywords": [<string keyword ที่ผู้ใช้บอกว่าชอบ/อยากได้ — บวกคะแนนเท่านั้น>],
  "hard_exclude_keywords": [<string คำหลักที่ "สั้นและกระชับที่สุด" ที่น่าจะปรากฏอยู่จริงในชื่อ/หมวดหมู่เมนู เมื่อผู้ใช้บอกว่า "ห้ามมีเลย"/"ไม่กินเด็ดขาด"/"งด" แบบเด็ดขาด แต่ไม่ใช่การแพ้อาหารทางการแพทย์ — ตัดคำฟุ่มเฟือยออก เช่น "ของดิบ" ให้ใช้ "ดิบ", "เนื้อหมู" ให้ใช้ "หมู", "อาหารทะเล" ให้แยกเป็น "กุ้ง","ปู","หอย","ปลา" — ตัดออกทั้งหมดเหมือน allergen>],
  "must_include_keywords": [<string keyword เมื่อผู้ใช้บอกว่า "กินแค่", "เอาเฉพาะ", "only" — ตัดทุกอย่างที่ไม่ตรงกับคำเหล่านี้ออกทั้งหมด>],
  "min_items": <number หรือ null>,
  "max_items": <number หรือ null>,
  "num_people": <number คนที่รับประทาน หรือ null — เช่น "2 คน", "กินกัน 4 คน", "คนเดียว" -> 1>,
  "allergy_check_answered": <true เมื่อข้อความนี้เป็นคำตอบของคำถาม "ไม่ชอบทานอะไร/แพ้อะไรไหม"
    ไม่ว่าคำตอบจะเป็นอะไรก็ตาม รวมถึง "ไม่มี"/"ไม่แพ้อะไร" ด้วย (ต้องถือว่าตอบแล้ว
    ไม่ใช่แค่ตอนที่มี allergens/dislikes เท่านั้น) มิฉะนั้น false>,
  "wants_dessert": <true/false เมื่อผู้ใช้ตอบคำถาม "รับของหวานไหม" อย่างชัดเจน
    (เช่น "เอา"/"รับ" -> true, "ไม่เอา"/"ไม่รับ" -> false) มิฉะนั้น null>,
  "drink_selection": [<string ชื่อเครื่องดื่มที่ผู้ใช้เลือกจากเมนูเครื่องดื่ม
    เช่น "ชาเขียวร้อน", "โค้ก", "น้ำส้ม" เมื่อตอบคำถาม "รับน้ำอะไรบ้าง">],
  "drink_quantity": <number จำนวนแก้วเครื่องดื่มที่ผู้ใช้ระบุ หรือ null — เป็นคนละ
    คำถามกับ "รับน้ำอะไรบ้าง" เสมอ (ถามชื่อก่อน แล้วจึงถามจำนวนแยกต่างหาก)>,
  "drinks_budget_mode": <"within" เมื่อผู้ใช้บอกว่าให้รวมค่าเครื่องดื่ม/ของหวาน
    อยู่ในงบเดิม, "separate" เมื่อบอกว่าให้แยกคิดต่างหาก (ไม่รวมในงบ), หรือ null
    ถ้ายังไม่ได้ตอบคำถามนี้>,
  "dessert_selection": [<string ชื่อของหวานที่ผู้ใช้เลือก เมื่อตอบว่ารับของหวาน
    และระบุชนิดด้วย เช่น "โมจิ", "ไอศกรีม">],
  "dessert_quantity": <number จำนวนชิ้นของหวานที่ผู้ใช้ระบุ หรือ null — เป็นคนละ
    คำถามกับ "รับของหวานเมนูไหน" เสมอ (ถามชื่อก่อน แล้วจึงถามจำนวนแยกต่างหาก)>,
  "intent": <หนึ่งใน "optimize", "search", "info", "clarify_answer">
}

หมายเหตุสำคัญ: "ไม่ชอบ" / "เบื่อ" -> dislikes (soft). "ไม่กินเลย" / "ไม่เอาเลย" /
"งด" / "ห้ามมี" ของสิ่งที่ไม่ใช่สารก่อภูมิแพ้ทางการแพทย์ -> hard_exclude_keywords
(hard). "ชอบ" / "อยากได้" -> preferred_keywords (soft). "กินแค่" / "เอาเฉพาะ" /
"only" -> must_include_keywords (hard, ตัดอย่างอื่นออกทั้งหมด).

สำคัญมาก — การตีความข้อความสั้นๆ ตามบริบท: ข้อความของผู้ใช้บางครั้งสั้นมาก
(เช่น "ไม่", "ไม่มี", "ค่ะ", ตัวเลขเดี่ยวๆ, ชื่อเครื่องดื่มเดี่ยวๆ) ซึ่งความหมาย
ขึ้นอยู่กับว่า "ระบบเพิ่งถามอะไรไป" — ถ้าพรอมป์นี้มีบรรทัด
"[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'X']" กำกับไว้ก่อนข้อความผู้ใช้ ให้ตีความ
คำตอบสั้นๆ นั้นโดยอิง X เสมอ:
- X="allergy": คำตอบปฏิเสธ ("ไม่", "ไม่มี", "เปล่า", "ไม่แพ้") -> allergy_check_answered=true
  (allergens/dislikes ปล่อยว่าง); คำตอบที่ระบุของ -> allergy_check_answered=true
  พร้อมใส่ allergens/dislikes ตามที่ระบุ
- X="num_people": ตัวเลขเดี่ยวๆ หรือ "คนเดียว"/"N คน" -> num_people
- X="drinks": ชื่อเครื่องดื่ม หรือ "อะไรก็ได้" -> drink_selection (ใส่ "ชาเขียวร้อน"
  ถ้าตอบว่าอะไรก็ได้)
- X="drink_quantity": ตัวเลขเดี่ยวๆ -> drink_quantity (ห้ามใส่ใน drink_selection)
- X="drinks_budget_mode": "รวม"/"ในงบเดิม" -> drinks_budget_mode="within";
  "แยก"/"ไม่รวม"/"นอกงบ" -> drinks_budget_mode="separate"
- X="dessert": "เอา"/"รับ"/ชื่อของหวาน -> wants_dessert=true (+dessert_selection
  ถ้าระบุชนิด); "ไม่เอา"/"ไม่รับ"/"พอแล้ว" -> wants_dessert=false
- X="dessert_selection": ชื่อของหวาน -> dessert_selection (wants_dessert เป็น
  true อยู่แล้วจากคำถามก่อนหน้า ไม่ต้องตั้งซ้ำ)
- X="dessert_quantity": ตัวเลขเดี่ยวๆ -> dessert_quantity

ตัวอย่าง (ทุกฟิลด์ที่ไม่ได้พูดถึงในข้อความให้เป็นค่า default: null/false/[]):
ข้อความ: "จัดเซ็ตงบ 300 บาท แพ้กุ้ง ชอบแซลมอน"
JSON: {"budget": 300, "budget_delta": null, "budget_change_unclear": false, "allergens": ["crustacean"], "dislikes": [], "preferred_keywords": ["แซลมอน"], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "แพ้ปลาด้วยนะ"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": ["fish"], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "งบ 1000 กินแค่กุ้งกับปลา ไม่กินของดิบเลย"
JSON: {"budget": 1000, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": ["ดิบ"], "must_include_keywords": ["กุ้ง", "ปลา"], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "ไม่ชอบหอยเท่าไหร่"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": ["หอย"], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "เพิ่มงบอีก 100 บาท"
JSON: {"budget": null, "budget_delta": 100, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "เพิ่มงบประมาณอีกหน่อย" (ไม่มีตัวเลขเลย)
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": true, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'num_people']\nกินกัน 3 คน"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": 3, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'allergy']\nไม่มีค่ะ ไม่แพ้อะไร"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": true, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'allergy']\nไม่" (สั้นมาก แต่บริบทบอกว่ากำลังตอบคำถามแพ้อาหาร — ต้องตีความว่าตอบแล้วว่าไม่มี)
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": true, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drinks']\nรับชาเขียวร้อนค่ะ"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": ["ชาเขียวร้อน"], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drink_quantity']\n2 แก้ว"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": 2, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drinks_budget_mode']\nรวมในงบเดิมได้เลย"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": "within", "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'dessert']\nเอาของหวานด้วย เอาโมจิ"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": true, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": ["โมจิ"], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'dessert']\nไม่เอา"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": false, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'dessert_quantity']\n3 ชิ้น"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": 3, "intent": "clarify_answer"}"""


class BudgeteerAgent:
    """Wraps the LangGraph ReAct agent + BudgeteerState into a simple chat API."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        api_key = api_key or os.getenv("OPENAI_API_KEY")
        model_name = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        self.llm = ChatOpenAI(model=model_name, temperature=0, api_key=api_key)
        self.state = BudgeteerState()
        try:
            # langgraph >= 0.2.6x
            self.agent = create_react_agent(self.llm, AGENT_TOOLS, prompt=SYSTEM_PROMPT)
        except TypeError:
            # older langgraph releases used `state_modifier` for the system prompt
            self.agent = create_react_agent(self.llm, AGENT_TOOLS, state_modifier=SYSTEM_PROMPT)

    # ------------------------------------------------------------------
    def _extract_intent(self, user_message: str, last_asked_field: Optional[str] = None) -> Dict[str, Any]:
        """Ask the LLM to turn free text into structured JSON.

        `last_asked_field` is what the system's own previous turn asked about
        (e.g. "allergy", "drinks") — without it, a bare "ไม่"/"ไม่มี" reply is
        ambiguous in isolation and the extractor can't tell what it's a reply
        to, which is exactly what caused the agent to loop on the allergy
        question forever regardless of the user's answer.

        Falls back to intent="info" (a safe no-op) if the model's output
        isn't valid JSON, so a parsing hiccup never crashes the app.
        """
        context_note = (
            f"[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง '{last_asked_field}']\n" if last_asked_field else ""
        )
        # Built with an f-string (not .format()) so the literal JSON braces in
        # EXTRACT_PROMPT's schema/examples are never mistaken for format fields.
        prompt = f"{EXTRACT_PROMPT}\n\nข้อความของผู้ใช้: {context_note}{user_message}\nJSON:"
        try:
            response = self.llm.invoke([SystemMessage(content=prompt)])
            text = response.content.strip()
            text = re.sub(r"^```(json)?", "", text.strip())
            text = re.sub(r"```$", "", text.strip())
            data = json.loads(text.strip())
            if not isinstance(data, dict):
                raise ValueError("extractor did not return a JSON object")
            return data
        except Exception:
            return {"intent": "info"}

    def _build_agent_context(self, extracted: Optional[Dict[str, Any]] = None) -> str:
        """A decision *hint* for the ReAct agent — advisory, not a forced flow.

        The LLM still makes the final call on which tool to use; this just
        saves it a reasoning step by summarizing what BudgeteerState already
        knows. `extracted` is this turn's raw extraction dict (not persisted
        state), used to catch turn-specific signals like a budget-change
        request with no resolvable number.
        """
        if extracted and extracted.get("budget_change_unclear"):
            self.state.last_asked_field = "budget"
            hint = (
                "ผู้ใช้พูดถึงการเพิ่ม/ลด/เปลี่ยนงบประมาณ แต่ไม่ได้บอกจำนวนเป็นตัวเลข "
                f"งบปัจจุบันที่ยังใช้อยู่คือ {self.state.budget} บาท (ยังไม่เปลี่ยน) "
                "ห้ามเรียก build_optimal_set ซ้ำด้วยงบเดิมโดยไม่ถาม — ให้เรียก "
                "request_clarification(missing=['budget']) เพื่อถามว่าต้องการเปลี่ยนงบ"
                "เป็นเท่าไหร่ หรือเพิ่ม/ลดกี่บาท ก่อนคำนวณใหม่"
            )
        elif self.state.budget is None or self.state.budget <= 0:
            self.state.last_asked_field = "budget"
            hint = (
                "ยังไม่ทราบงบประมาณของผู้ใช้ แนะนำให้เรียก request_clarification "
                "(missing=['budget']) ก่อนเรียก build_optimal_set"
            )
        elif self.state.needs_num_people():
            self.state.last_asked_field = "num_people"
            hint = (
                f"ทราบงบประมาณแล้ว ({self.state.budget} บาท) แต่ยังไม่ทราบจำนวนคนที่รับประทาน "
                "ห้ามเรียก build_optimal_set ตอนนี้ — ให้เรียก request_clarification "
                "(missing=['num_people']) ถามจำนวนคนก่อนเสมอ (จำนวนคนมีผลต่อการจัดชุด "
                "เช่น จำนวนเครื่องดื่มที่ต้องเท่ากับจำนวนคน)"
            )
        elif self.state.needs_allergy_check():
            self.state.last_asked_field = "allergy"
            hint = (
                f"ทราบงบประมาณ ({self.state.budget} บาท) และจำนวนคน ({self.state.num_people} คน) แล้ว "
                "แต่ยังไม่เคยถามเรื่องแพ้อาหาร/ไม่ชอบทานอะไรในบทสนทนานี้ — ให้เรียก "
                "request_clarification (missing=['allergy']) ถามว่า \"มีอะไรที่ไม่ชอบทาน "
                "หรือแพ้อาหารประเภทไหนไหมครับ\" ก่อนเสมอ แม้ผู้ใช้จะยังไม่เคยพูดถึงเรื่องนี้เลยก็ตาม "
                "(ถ้าผู้ใช้ตอบว่าไม่มี ระบบจะถือว่าถามแล้วและไม่ถามซ้ำอีก)"
            )
        elif self.state.needs_drink_selection():
            self.state.last_asked_field = "drinks"
            hint = (
                "ทราบงบ/จำนวนคน/เรื่องแพ้อาหารครบแล้ว แต่ยังไม่ทราบว่าผู้ใช้ต้องการรับ"
                "เครื่องดื่มอะไร (เครื่องดื่มบังคับต้องมี ไม่ใช่ตัวเลือก) — ให้เรียก "
                "request_clarification (missing=['drinks']) ถามว่า \"รับเครื่องดื่มอะไรบ้างครับ\" "
                f"พร้อมแสดงรายการเมนูเครื่องดื่มที่มีจริงให้เลือก: {_menu_list_text('เครื่องดื่ม')} "
                "ก่อนเรียก build_optimal_set เสมอ ห้ามเดาให้เอง ถ้าผู้ใช้บอกว่าอะไรก็ได้ "
                "ให้ใช้ 'ชาเขียวร้อน' (ฟรี) เป็นค่าเริ่มต้น"
            )
        elif self.state.needs_drink_quantity():
            self.state.last_asked_field = "drink_quantity"
            hint = (
                f"ผู้ใช้เลือกเครื่องดื่มแล้ว ({', '.join(self.state.drink_selection)}) แต่ยังไม่ได้ระบุ"
                f"จำนวนแก้ว — ห้ามสมมติเอาเองว่าเท่ากับจำนวนคน ({self.state.num_people} คน) แม้จะเป็น"
                "ค่าที่พบบ่อยก็ตาม ให้เรียก request_clarification (missing=['drink_quantity']) ถามว่า "
                "\"ต้องการเครื่องดื่มนี้กี่แก้วครับ\" ก่อนเสมอ"
            )
        elif self.state.needs_drinks_budget_mode():
            self.state.last_asked_field = "drinks_budget_mode"
            hint = (
                f"ทราบตัวเลือกเครื่องดื่มแล้ว ({', '.join(self.state.drink_selection)}) แต่ยังไม่ทราบว่า "
                "ต้องการให้ค่าเครื่องดื่ม (และของหวานถ้ามี) รวมอยู่ในงบที่แจ้งไว้เดิม หรือคิดแยกต่างหาก "
                "— ให้เรียก request_clarification (missing=['drinks_budget_mode']) ถามว่า "
                "\"ต้องการให้ค่าเครื่องดื่มรวมอยู่ในงบเดิม หรือคิดแยกต่างหากดีครับ\" ก่อนเสมอ "
                "ห้ามสมมติเอาเองว่ารวมหรือแยก"
            )
        elif self.state.needs_dessert_confirmation():
            self.state.last_asked_field = "dessert"
            hint = (
                "ทราบงบ/จำนวนคน/แพ้อาหาร/เครื่องดื่ม/วิธีคิดค่าเครื่องดื่มครบแล้ว แต่ยังไม่เคยถามว่า"
                "ต้องการของหวานด้วยไหม — ให้เรียก request_clarification (missing=['dessert']) ถามว่า "
                f"\"รับของหวานด้วยไหมครับ\" พร้อมแสดงรายการของหวานที่มีจริง: "
                f"{_menu_list_text('ของหวาน')} ก่อนเสมอ (ของหวานเป็น option ห้ามใส่เข้าไปเองถ้า"
                "ยังไม่ถามยืนยัน)"
            )
        elif self.state.needs_dessert_selection():
            self.state.last_asked_field = "dessert_selection"
            hint = (
                "ผู้ใช้ตอบรับของหวานแล้วแต่ยังไม่ได้ระบุชนิด — ให้เรียก request_clarification "
                "(missing=['dessert_selection']) ถามว่า \"รับของหวานเมนูไหนดีครับ\" พร้อมแสดง"
                f"รายการของหวานที่มีจริง: {_menu_list_text('ของหวาน')} ก่อนเสมอ"
            )
        elif self.state.needs_dessert_quantity():
            self.state.last_asked_field = "dessert_quantity"
            hint = (
                f"ผู้ใช้เลือกของหวานแล้ว ({', '.join(self.state.dessert_selection)}) แต่ยังไม่ได้ระบุ"
                f"จำนวนชิ้น — ห้ามสมมติเอาเองว่าเท่ากับจำนวนคน ({self.state.num_people} คน) ให้เรียก "
                "request_clarification (missing=['dessert_quantity']) ถามว่า "
                "\"ต้องการของหวานนี้กี่ชิ้นครับ\" ก่อนเสมอ"
            )
        else:
            self.state.last_asked_field = None
            call_args = (
                f"budget={self.state.budget}, allergens={self.state.allergens}, "
                f"dislikes={self.state.dislikes}, preferred_keywords={self.state.preferred_keywords}, "
                f"hard_exclude_keywords={self.state.hard_exclude_keywords}, "
                f"must_include_keywords={self.state.must_include_keywords}, "
                f"min_items={self.state.min_items}, max_items={self.state.max_items}, "
                f"num_people={self.state.num_people}, drink_selection={self.state.drink_selection}, "
                f"drink_quantity={self.state.drink_quantity}, "
                f"drinks_separate_from_budget={str(self.state.drinks_budget_mode == 'separate').lower()}, "
                f"include_dessert={str(bool(self.state.wants_dessert)).lower()}, "
                f"dessert_selection={self.state.dessert_selection}, "
                f"dessert_quantity={self.state.dessert_quantity}"
            )
            hint = (
                "งบประมาณ จำนวนคน การแพ้อาหาร เครื่องดื่ม (รวมวิธีคิดค่าเครื่องดื่ม) และของหวาน "
                "ครบถ้วนแล้ว ห้ามเรียก request_clarification อีก แม้ข้อความล่าสุดของผู้ใช้จะสั้นๆ "
                "(เช่น เพิ่ม allergen หรือ preference อย่างเดียว) ก็ตาม — ให้เรียกด้วยพารามิเตอร์นี้ทันที:\n"
                f"build_optimal_set({call_args})\n"
                f"ตามด้วย verify_result(budget={self.state.budget}, allergens={self.state.allergens}) เสมอก่อนตอบ\n"
                "อย่าลืม: hard_exclude_keywords และ must_include_keywords เป็นข้อจำกัดเด็ดขาด "
                "(ตัดออกทั้งชุด) ไม่ใช่แค่คะแนน — ถ้ามีค่าในนี้ ต้องส่งเข้า build_optimal_set ด้วยเสมอ "
                "และคำตอบสุดท้ายต้องระบุจำนวนจานทั้งหมดที่เลือกให้ชัดเจน (และแจ้งด้วยว่าค่าเครื่องดื่ม/"
                "ของหวานรวมในงบหรือคิดแยกต่างหาก ถ้าคิดแยก ให้บอกยอดรวมจริงที่เกินงบไว้ด้วย)"
            )
        return f"[คำแนะนำเชิงบริบทจากระบบ — ใช้ประกอบการตัดสินใจ ไม่ใช่คำสั่งบังคับ]\n{hint}"

    # ------------------------------------------------------------------
    def chat(self, user_message: str) -> str:
        """Run one full turn: extract -> update state -> hint -> ReAct -> answer."""
        self.state.add_message("user", user_message)

        extracted = self._extract_intent(user_message, self.state.last_asked_field)
        extracted = _sanitize_extraction(extracted, self.state.last_asked_field, user_message)
        self.state.update_from_extraction(extracted)

        context_hint = self._build_agent_context(extracted)
        composed_input = f"{context_hint}\n\nข้อความจากผู้ใช้: {user_message}"

        result = self.agent.invoke({"messages": [HumanMessage(content=composed_input)]})
        answer = result["messages"][-1].content

        self.state.add_message("assistant", answer)
        self.state.last_result = get_last_result()
        return answer

    def chat_stream(self, user_message: str) -> Iterator[str]:
        """Streaming version of chat() — yields text chunks for the Streamlit UI."""
        self.state.add_message("user", user_message)

        extracted = self._extract_intent(user_message, self.state.last_asked_field)
        extracted = _sanitize_extraction(extracted, self.state.last_asked_field, user_message)
        self.state.update_from_extraction(extracted)

        context_hint = self._build_agent_context(extracted)
        composed_input = f"{context_hint}\n\nข้อความจากผู้ใช้: {user_message}"

        full_text = ""
        for chunk, _metadata in self.agent.stream(
            {"messages": [HumanMessage(content=composed_input)]},
            stream_mode="messages",
        ):
            if isinstance(chunk, AIMessage) and chunk.content:
                full_text += chunk.content
                yield chunk.content

        self.state.add_message("assistant", full_text)
        self.state.last_result = get_last_result()
