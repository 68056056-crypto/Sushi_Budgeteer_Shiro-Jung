"""
state.py — Agent State Management สำหรับ Sushi-Budgeteer

เก็บ context ระหว่างสนทนาทั้งหมด ได้แก่:
  - budget         : งบประมาณของผู้ใช้
  - allergens      : รายการ allergen (hard constraint — ความปลอดภัย)
  - dislikes       : รายการที่ไม่ชอบ (soft constraint — preference)
  - preferences    : keyword ที่ชอบ
  - min_items      : จำนวนจานขั้นต่ำ
  - max_items      : จำนวนจานสูงสุด
  - last_result    : ผลลัพธ์การจัดเซ็ตล่าสุด
  - conversation   : ประวัติข้อความทั้งหมด (LangChain message format)
  - clarifications : สิ่งที่ถามผู้ใช้ไปแล้ว (ป้องกันถามซ้ำ)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from langchain_core.messages import BaseMessage


@dataclass
class BudgeteerState:
    """
    State object ที่ Agent ใช้ตลอดการสนทนา
    ถูก update ทุกครั้งที่ผู้ใช้ให้ข้อมูลใหม่
    """

    # --- Core constraints ---
    budget: int | None = None
    allergens: list[str] = field(default_factory=list)
    dislikes: list[str] = field(default_factory=list)
    preferences: list[str] = field(default_factory=list)
    min_items: int = 1
    max_items: int = 20
    require_categories: list[str] = field(default_factory=list)

    # --- Session memory ---
    last_result: dict[str, Any] | None = None
    conversation: list[BaseMessage] = field(default_factory=list)
    clarifications_asked: set[str] = field(default_factory=set)

    # --- Flags ---
    budget_confirmed: bool = False
    allergens_confirmed: bool = False

    def update_from_extraction(self, extracted: dict[str, Any]) -> list[str]:
        """
        รับ dict ที่ LLM extract จาก user message แล้ว update state
        คืน list ของ field ที่เพิ่งถูก update (เพื่อ log)

        Expected keys (ทั้งหมด optional):
            budget, allergens, dislikes, preferences,
            min_items, max_items, require_categories
        """
        updated = []

        if "budget" in extracted and extracted["budget"] is not None:
            try:
                self.budget = int(extracted["budget"])
                self.budget_confirmed = True
                updated.append("budget")
            except (ValueError, TypeError):
                pass

        if "allergens" in extracted and extracted["allergens"]:
            new = [a.lower().strip() for a in extracted["allergens"] if a.strip()]
            # merge — ไม่ลบของเก่า เพราะ allergen สำคัญมาก
            for a in new:
                if a not in self.allergens:
                    self.allergens.append(a)
            self.allergens_confirmed = True
            updated.append("allergens")

        if "dislikes" in extracted and extracted["dislikes"]:
            new = [d.lower().strip() for d in extracted["dislikes"] if d.strip()]
            for d in new:
                if d not in self.dislikes:
                    self.dislikes.append(d)
            updated.append("dislikes")

        if "preferences" in extracted and extracted["preferences"]:
            new = [p.lower().strip() for p in extracted["preferences"] if p.strip()]
            for p in new:
                if p not in self.preferences:
                    self.preferences.append(p)
            updated.append("preferences")

        if "min_items" in extracted and extracted["min_items"] is not None:
            try:
                self.min_items = max(1, int(extracted["min_items"]))
                updated.append("min_items")
            except (ValueError, TypeError):
                pass

        if "max_items" in extracted and extracted["max_items"] is not None:
            try:
                self.max_items = max(self.min_items, int(extracted["max_items"]))
                updated.append("max_items")
            except (ValueError, TypeError):
                pass

        if "require_categories" in extracted and extracted["require_categories"]:
            self.require_categories = extracted["require_categories"]
            updated.append("require_categories")

        return updated

    def get_missing_required(self) -> list[str]:
        """คืน list ของ field ที่จำเป็นแต่ยังไม่มีข้อมูล"""
        missing = []
        if self.budget is None:
            missing.append("budget")
        return missing

    def is_ready_to_optimize(self) -> bool:
        """True ถ้ามีข้อมูลครบพอสำหรับจัดเซ็ตได้"""
        return self.budget is not None and self.budget > 0

    def to_summary(self) -> str:
        """สรุป state ปัจจุบันเป็น text สำหรับแสดงใน UI"""
        lines = []
        lines.append(f"💰 งบประมาณ: {self.budget} บาท" if self.budget else "💰 งบประมาณ: ยังไม่ระบุ")
        if self.allergens:
            lines.append(f"🚫 แพ้อาหาร: {', '.join(self.allergens)}")
        if self.dislikes:
            lines.append(f"😕 ไม่ชอบ: {', '.join(self.dislikes)}")
        if self.preferences:
            lines.append(f"❤️ ชอบ: {', '.join(self.preferences)}")
        lines.append(f"🍣 จำนวนจาน: {self.min_items}–{self.max_items} จาน")
        return "\n".join(lines)

    def reset(self):
        """Reset state ทั้งหมด (เริ่มการสนทนาใหม่)"""
        self.budget = None
        self.allergens = []
        self.dislikes = []
        self.preferences = []
        self.min_items = 1
        self.max_items = 20
        self.require_categories = []
        self.last_result = None
        self.conversation = []
        self.clarifications_asked = set()
        self.budget_confirmed = False
        self.allergens_confirmed = False
