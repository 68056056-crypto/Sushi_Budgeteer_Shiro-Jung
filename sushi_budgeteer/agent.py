"""
agent.py — Sushi-Budgeteer Main Agent

Architecture: ReAct Agent (Reasoning + Acting)
  LLM ตัดสินใจว่าจะเรียก Tool ไหน → รับผล → ตัดสินใจต่อ
  ไม่ใช่ fixed pipeline — Agent คิดเองทุกขั้นตอน

Decision Logic:
  1. Extract intent + constraints จาก user message
  2. Update state (budget, allergens, dislikes, preferences)
  3. ถ้าข้อมูลไม่ครบ → เรียก request_clarification
  4. ถ้าครบ → เรียก build_optimal_set (ซึ่งใช้ filter + DP ภายใน)
  5. เรียก verify_result เสมอก่อนตอบ
  6. ถ้า verify ไม่ผ่าน → วิเคราะห์ปัญหาแล้วปรับ parameter ใหม่ ไม่ใช่แค่ส่งผลที่ผิดออกไป

Tool Decision Flow:
  search_menu_items    ← เมื่อผู้ใช้ถามเกี่ยวกับเมนูเฉพาะ / สำรวจ
  filter_constraints   ← เรียกอัตโนมัติก่อน optimize (embedded ใน build_optimal_set)
  build_optimal_set    ← เมื่อมีงบและพร้อม optimize
  verify_result        ← เรียกทุกครั้งหลัง build
  request_clarification← เมื่อข้อมูลไม่ครบ / ขัดแย้ง / งบน้อยเกินไป
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Iterator

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import BaseMessage

from tools import AGENT_TOOLS
from state import BudgeteerState

# ---------------------------------------------------------------------------
# System Prompt — บอก Agent ว่าเป็นใคร มี tools อะไร และ logic การตัดสินใจ
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """คุณคือ Sushi-Budgeteer AI Agent ผู้ช่วยจัดเซ็ตเมนูซูชิของร้าน Sushiro ตามงบประมาณและความต้องการของผู้ใช้

## บทบาทและความสามารถ

คุณมี Tools 5 อย่างที่ใช้ตัดสินใจเรียกตามสถานการณ์:

1. **search_menu_items** — ค้นหาเมนูตาม keyword/category/ราคา
   → เรียกเมื่อ: ผู้ใช้ถามเมนูเฉพาะ, สำรวจตัวเลือก, หรือต้องการรู้ว่ามีอะไรบ้าง

2. **filter_constraints** — กรองเมนูตาม allergen (hard) และ dislike (soft)
   → เรียกเมื่อ: ต้องการดูว่าเมนูไหนที่ผู้ใช้ทานได้ก่อน optimize

3. **build_optimal_set** — จัดชุดเมนูที่คุ้มค่าที่สุดด้วย Dynamic Programming
   → เรียกเมื่อ: มีงบประมาณและพร้อม optimize
   → ภายในนี้ทำ filter + DP อัตโนมัติ

4. **verify_result** — ตรวจสอบผลลัพธ์ก่อนส่งให้ผู้ใช้
   → เรียก**ทุกครั้ง**หลังจาก build_optimal_set
   → ถ้าไม่ผ่าน: วิเคราะห์ปัญหาแล้วปรับ parameter ใหม่

5. **request_clarification** — ถามผู้ใช้เมื่อข้อมูลไม่ครบ
   → เรียกเมื่อ: ไม่มีงบ, งบน้อยเกินไป, ขัดแย้ง

6. **semantic_search_menu** — ค้นหาเมนูด้วยความหมาย (RAG / FAISS vector search)
   → เรียกเมื่อ: ผู้ใช้อธิบายรสชาติ/ความรู้สึก ไม่ใช่ชื่อเมนูตรงๆ
   → เช่น "อยากได้อะไรมันๆ เข้มข้น", "ของหวานเบาๆ", "อาหารทอดกรอบ"
   → search_menu_items หาไม่เจอ แต่ semantic search หาได้

7. **rag_augmented_build** — จัดชุดเมนูโดยใช้ RAG หา candidate pool ก่อน แล้วส่งเข้า DP
   → เรียกเมื่อ: ผู้ใช้อธิบายความต้องการเป็นประโยคยาว / เชิงความหมาย
   → เช่น "อยากได้เมนูรสเข้มข้น มีทั้งปลาดิบและของทอด งบ 400 บาท"

## กฎการตัดสินใจ (Decision Logic)

**กฎที่ 1: ลำดับการ verify allergen**
- allergen = ห้ามเด็ดขาด (ความปลอดภัย) → ถูกกรองออกก่อนทุกอย่าง
- dislike = ไม่ชอบ (preference) → ยังคงอยู่ใน pool แต่ได้ score ต่ำกว่า
- อย่าสับสนระหว่างสองอย่างนี้

**กฎที่ 2: เมื่องบไม่พอ**
- ถ้า budget < ราคาเมนูที่ถูกสุด → เรียก request_clarification ทันที
- ถ้าผลลัพธ์ได้จำนวนจานน้อยกว่า min_items → แจ้งผู้ใช้พร้อมทางเลือก

**กฎที่ 3: verify ก่อนตอบเสมอ**
- หลัง build_optimal_set ต้องเรียก verify_result เสมอ
- ถ้า verify ไม่ผ่าน → อย่าส่งผลนั้นให้ผู้ใช้

**กฎที่ 4: จำ state ตลอดบทสนทนา**
- budget, allergens, dislikes, preferences ที่ผู้ใช้บอกไว้ก่อนหน้า ยังใช้ต่อในทุก turn
- ผู้ใช้ไม่ต้องบอกซ้ำ เว้นแต่จะแจ้งเปลี่ยน

**กฎที่ 5: ห้ามเดา allergen จาก description**
- ใช้ข้อมูล allergens_verified จากฐานข้อมูลเท่านั้น
- ต้องมี disclaimer ทุกครั้งที่ตอบเรื่อง allergen

**กฎที่ 6: เลือกระหว่าง keyword search กับ semantic search**
- ถ้าผู้ใช้พูดชื่อเมนูตรงๆ หรือ ingredient → ใช้ `search_menu_items` (เร็วกว่า)
- ถ้าผู้ใช้อธิบายรสชาติ/ความรู้สึก/บรรยากาศ → ใช้ `semantic_search_menu`
- ถ้าผู้ใช้ optimize พร้อมคำอธิบายเชิงความหมาย → ใช้ `rag_augmented_build` แทน `build_optimal_set`

## Format การตอบ

เมื่อจัดเซ็ตสำเร็จ ให้แสดง:
1. รายการเมนูที่เลือก (ชื่อไทย + ราคา)
2. ยอดรวม และเปอร์เซ็นต์การใช้งบ
3. หมวดหมู่ที่ครอบคลุม
4. Disclaimer เรื่อง allergen (ถ้ามีการกรอง)

ตอบเป็นภาษาไทยเสมอ ยกเว้นชื่อเมนูภาษาอังกฤษ

## Disclaimer บังคับ (allergen)
"⚠️ ข้อมูล allergen มาจาก dataset จำลองเท่านั้น ไม่รับประกันการปนเปื้อนจริงในร้าน
กรุณาแจ้งพนักงานโดยตรงก่อนสั่งอาหารหากมีอาการแพ้รุนแรง"
"""

# ---------------------------------------------------------------------------
# Intent & Constraint Extractor — LLM แยก structured data จาก free text
# ---------------------------------------------------------------------------

EXTRACT_PROMPT = """แยก intent และข้อมูลต่อไปนี้จากข้อความผู้ใช้ แล้ว return เป็น JSON เท่านั้น (ไม่มี text อื่น)

ข้อความ: "{user_message}"

Context ปัจจุบัน:
- งบปัจจุบัน: {current_budget}
- allergen ที่แพ้อยู่แล้ว: {current_allergens}
- ไม่ชอบ: {current_dislikes}

Schema ที่ต้อง return:
{{
  "intent": "optimize" | "search" | "info" | "clarify" | "reset" | "compare",
  "budget": <int หรือ null>,
  "allergens": <list[str] — allergen ที่แพ้ เช่น ["fish","gluten"] หรือ []>,
  "dislikes": <list[str] — สิ่งที่ไม่ชอบ เช่น ["ปลาหมึก"] หรือ []>,
  "preferences": <list[str] — สิ่งที่ชอบ เช่น ["แซลมอน","กุ้ง"] หรือ []>,
  "min_items": <int หรือ null>,
  "max_items": <int หรือ null>,
  "require_categories": <list[str] หรือ []>,
  "search_keyword": <str หรือ null>,
  "remove_allergens": <list[str] — allergen ที่ต้องการลบออก เช่น ["fish"]>,
  "remove_dislikes": <list[str] — dislike ที่ต้องการลบออก>
}}

กฎการแปลง allergen (ใช้ tag ภาษาอังกฤษเหล่านี้เท่านั้น):
ปลา/fish → "fish"
กุ้ง/shrimp/กุ้งมังกร → "crustacean"
หอย/oyster/scallop/หมึก → "molluscs"
ไข่ → "egg"
นม/dairy → "milk"
แป้งสาลี/wheat/กลูเตน → "gluten"
ถั่วเหลือง/soy sauce → "soy"
งา/sesame → "sesame"
หมู/pork → "pork"

intent:
- "optimize"     = ผู้ใช้ต้องการจัดเซ็ตเมนู (ด้วย keyword ตรงๆ)
- "rag_optimize" = ผู้ใช้ต้องการจัดเซ็ตโดยอธิบายด้วยความรู้สึก/รสชาติ
- "search"       = ผู้ใช้ถามเกี่ยวกับเมนูเฉพาะ (ชื่อหรือ ingredient ตรงๆ)
- "rag_search"   = ผู้ใช้ถามเมนูด้วยคำอธิบายเชิงความหมาย เช่น "อะไรมันๆ"
- "info"         = ถามข้อมูลทั่วไป
- "clarify"      = ตอบคำถามที่ agent ถาม
- "reset"        = ต้องการเริ่มใหม่
- "compare"      = ต้องการเปรียบเทียบ DP vs random"""


# ---------------------------------------------------------------------------
# BudgeteerAgent — Main class
# ---------------------------------------------------------------------------

class BudgeteerAgent:
    """
    Main Agent class ที่รวม:
    - LLM (ChatOpenAI) สำหรับ reasoning
    - LangGraph ReAct agent สำหรับ tool calling
    - BudgeteerState สำหรับ session memory
    - Intent extractor สำหรับ structured parsing
    """

    def __init__(self, model: str = "gpt-4o-mini", temperature: float = 0.0):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "ไม่พบ OPENAI_API_KEY — กรุณา set environment variable ก่อนใช้งาน"
            )

        self.llm = ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
        )

        # LLM สำหรับ extract intent (ใช้ model เดียวกัน)
        self.extractor_llm = ChatOpenAI(
            model=model,
            temperature=0.0,
            api_key=api_key,
        )

        # สร้าง ReAct agent พร้อม tools และ system prompt
        # LangGraph >= 0.4 ใช้ prompt parameter (state_modifier ถูกลบแล้ว)
        self.react_agent = create_react_agent(
            model=self.llm,
            tools=AGENT_TOOLS,
            prompt=SYSTEM_PROMPT,
        )

        self.state = BudgeteerState()

    # ------------------------------------------------------------------
    # Intent extraction
    # ------------------------------------------------------------------

    def _extract_intent(self, user_message: str) -> dict[str, Any]:
        """ใช้ LLM แปลง free-text เป็น structured dict"""
        prompt = EXTRACT_PROMPT.format(
            user_message=user_message,
            current_budget=self.state.budget or "ยังไม่ระบุ",
            current_allergens=", ".join(self.state.allergens) or "ไม่มี",
            current_dislikes=", ".join(self.state.dislikes) or "ไม่มี",
        )
        response = self.extractor_llm.invoke([HumanMessage(content=prompt)])
        raw = response.content.strip()

        # ลอง parse JSON
        try:
            # ถ้ามี markdown code block ให้ strip ออก
            raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
            return json.loads(raw)
        except json.JSONDecodeError:
            # fallback: return intent=info เพื่อไม่ crash
            return {
                "intent": "info",
                "budget": None,
                "allergens": [],
                "dislikes": [],
                "preferences": [],
                "min_items": None,
                "max_items": None,
                "require_categories": [],
                "search_keyword": None,
                "remove_allergens": [],
                "remove_dislikes": [],
            }

    # ------------------------------------------------------------------
    # State update helpers
    # ------------------------------------------------------------------

    def _apply_removals(self, extracted: dict[str, Any]):
        """จัดการ remove_allergens และ remove_dislikes"""
        for a in extracted.get("remove_allergens", []):
            a = a.lower().strip()
            if a in self.state.allergens:
                self.state.allergens.remove(a)

        for d in extracted.get("remove_dislikes", []):
            d = d.lower().strip()
            if d in self.state.dislikes:
                self.state.dislikes.remove(d)

    # ------------------------------------------------------------------
    # Build context message สำหรับส่งให้ ReAct agent
    # ------------------------------------------------------------------

    def _build_agent_context(self, user_message: str, extracted: dict[str, Any]) -> str:
        """
        สร้าง augmented message ที่บอก Agent ว่า:
        - state ปัจจุบันคืออะไร
        - intent คืออะไร
        - ควรเรียก tool ไหน

        นี่คือ "decision hint" — ไม่ใช่ fixed flow แต่ช่วย LLM ตัดสินใจได้ถูกต้องขึ้น
        """
        context_parts = [
            f"## ข้อความผู้ใช้\n{user_message}",
            f"\n## State ปัจจุบัน\n{self.state.to_summary()}",
        ]

        intent = extracted.get("intent", "info")
        context_parts.append(f"\n## Intent ที่ตรวจพบ: {intent}")

        # บอก Agent ชัดเจนว่าควรทำอะไร
        if intent == "optimize":
            if not self.state.is_ready_to_optimize():
                context_parts.append(
                    "\n## คำแนะนำสำหรับ Agent\n"
                    "ยังไม่มีงบประมาณ → เรียก `request_clarification` "
                    'ด้วย missing_fields=["budget"]'
                )
            else:
                context_parts.append(
                    "\n## คำแนะนำสำหรับ Agent\n"
                    f"มีข้อมูลครบ → เรียก `build_optimal_set` ด้วย:\n"
                    f"  budget={self.state.budget}\n"
                    f"  allergens={self.state.allergens}\n"
                    f"  dislikes={self.state.dislikes}\n"
                    f"  preferred_keywords={self.state.preferences}\n"
                    f"  min_items={self.state.min_items}\n"
                    f"  max_items={self.state.max_items}\n"
                    f"จากนั้น**ต้อง**เรียก `verify_result` ก่อนตอบเสมอ"
                )

        elif intent == "rag_optimize":
            if not self.state.is_ready_to_optimize():
                context_parts.append(
                    "\n## คำแนะนำสำหรับ Agent\n"
                    "ยังไม่มีงบประมาณ → เรียก `request_clarification` "
                    'ด้วย missing_fields=["budget"]'
                )
            else:
                pref_desc = " ".join(self.state.preferences) or user_message
                context_parts.append(
                    "\n## คำแนะนำสำหรับ Agent\n"
                    f"ผู้ใช้อธิบายความต้องการเชิงความหมาย → เรียก `rag_augmented_build` ด้วย:\n"
                    f"  budget={self.state.budget}\n"
                    f"  preference_description=\"{pref_desc}\"\n"
                    f"  allergens={self.state.allergens}\n"
                    f"  dislikes={self.state.dislikes}\n"
                    f"  min_items={self.state.min_items}\n"
                    f"  max_items={self.state.max_items}\n"
                    f"จากนั้น**ต้อง**เรียก `verify_result` ก่อนตอบเสมอ"
                )

        elif intent == "search":
            kw = extracted.get("search_keyword", "")
            context_parts.append(
                f"\n## คำแนะนำสำหรับ Agent\n"
                f"ผู้ใช้ต้องการค้นหาเมนู → เรียก `search_menu_items` "
                f'ด้วย keyword="{kw}"'
            )

        elif intent == "rag_search":
            context_parts.append(
                f"\n## คำแนะนำสำหรับ Agent\n"
                f"ผู้ใช้ค้นหาด้วยความหมาย → เรียก `semantic_search_menu` ด้วย:\n"
                f"  query=\"{user_message}\"\n"
                f"  allergens_exclude={self.state.allergens}\n"
                f"  top_k=5"
            )

        elif intent == "compare":
            context_parts.append(
                "\n## คำแนะนำสำหรับ Agent\n"
                "ผู้ใช้ต้องการเปรียบเทียบ DP vs Random → "
                "เรียก `build_optimal_set` แล้วอธิบายว่าทำไม DP ถึงดีกว่า random"
            )

        elif intent == "reset":
            context_parts.append(
                "\n## คำแนะนำสำหรับ Agent\n"
                "ผู้ใช้ต้องการเริ่มใหม่ → แจ้งว่า reset แล้วและถามข้อมูลใหม่"
            )

        return "\n".join(context_parts)

    # ------------------------------------------------------------------
    # Main chat method
    # ------------------------------------------------------------------

    def chat(self, user_message: str) -> str:
        """
        รับ user message แล้วคืน agent response

        Flow:
          1. Extract intent + constraints จาก message
          2. Apply removals (ถ้ามี)
          3. Update state
          4. Handle reset
          5. Build augmented context
          6. ส่งให้ ReAct agent ตัดสินใจเรียก tools
          7. คืน final response
        """
        # Step 1: Extract structured data
        extracted = self._extract_intent(user_message)

        # Step 2: Apply removals before update
        self._apply_removals(extracted)

        # Step 3: Update state
        if extracted.get("intent") != "reset":
            updated_fields = self.state.update_from_extraction(extracted)

        # Step 4: Handle reset
        if extracted.get("intent") == "reset":
            self.state.reset()
            return (
                "🔄 รีเซ็ตการสนทนาแล้ว\n\n"
                "บอกงบประมาณและความต้องการได้เลยครับ เช่น\n"
                "\"ต้องการจัดเซ็ตงบ 300 บาท ไม่กินปลาดิบ\""
            )

        # Step 5: Build context for agent
        augmented_message = self._build_agent_context(user_message, extracted)

        # Step 6: Add to conversation history
        self.state.conversation.append(HumanMessage(content=user_message))

        # Step 7: Run ReAct agent
        # LangGraph agent รับ messages list ซึ่งรวม history ไว้ด้วย
        messages_for_agent = [
            # ส่ง history เพื่อให้ agent จำ context
            *self.state.conversation[:-1],  # ยกเว้น message ล่าสุด
            HumanMessage(content=augmented_message),  # message ล่าสุดพร้อม context
        ]

        response = self.react_agent.invoke({"messages": messages_for_agent})

        # ดึง final AI message
        ai_messages = [m for m in response["messages"] if isinstance(m, AIMessage)]
        final_response = ai_messages[-1].content if ai_messages else "ขออภัย เกิดข้อผิดพลาด"

        # Step 8: บันทึก response ใน state
        self.state.conversation.append(AIMessage(content=final_response))

        return final_response

    # ------------------------------------------------------------------
    # Streaming support
    # ------------------------------------------------------------------

    def chat_stream(self, user_message: str) -> Iterator[str]:
        """
        Streaming version ของ chat() สำหรับ Streamlit
        yield token ทีละตัว
        """
        extracted = self._extract_intent(user_message)
        self._apply_removals(extracted)

        if extracted.get("intent") != "reset":
            self.state.update_from_extraction(extracted)

        if extracted.get("intent") == "reset":
            self.state.reset()
            yield "🔄 รีเซ็ตการสนทนาแล้ว\n\nบอกงบประมาณและความต้องการได้เลยครับ"
            return

        augmented_message = self._build_agent_context(user_message, extracted)
        self.state.conversation.append(HumanMessage(content=user_message))

        messages_for_agent = [
            *self.state.conversation[:-1],
            HumanMessage(content=augmented_message),
        ]

        full_response = ""
        for chunk in self.react_agent.stream({"messages": messages_for_agent}):
            # LangGraph stream ส่งมาเป็น dict ของ step
            if "agent" in chunk:
                for msg in chunk["agent"].get("messages", []):
                    if isinstance(msg, AIMessage) and msg.content:
                        delta = msg.content
                        if isinstance(delta, str):
                            full_response += delta
                            yield delta

        if full_response:
            self.state.conversation.append(AIMessage(content=full_response))

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def get_state_summary(self) -> str:
        return self.state.to_summary()

    def get_conversation_length(self) -> int:
        return len(self.state.conversation)
