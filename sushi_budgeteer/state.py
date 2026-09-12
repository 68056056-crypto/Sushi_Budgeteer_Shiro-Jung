"""BudgeteerState: session memory that persists across turns of a conversation.

The Agent is stateless by itself (LLM calls do not remember previous turns
unless we hand the context back in). This module is the "memory" that lets a
user say "budget 300" in one message and "I'm allergic to fish too" in the
next, without repeating everything each time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# Allergen tags recognised by the system. These must match the values found
# in the `allergens_verified` column of sushiro_menu_dataset.csv.
KNOWN_ALLERGENS = {
    "fish",
    "crustacean",
    "molluscs",
    "egg",
    "milk",
    "gluten",
    "soy",
    "sesame",
    "pork",
}


@dataclass
class BudgeteerState:
    """Conversation memory for a single user session."""

    budget: Optional[float] = None
    allergens: List[str] = field(default_factory=list)
    dislikes: List[str] = field(default_factory=list)
    preferred_keywords: List[str] = field(default_factory=list)
    # Hard constraints beyond the fixed allergen vocabulary. Unlike
    # `dislikes` (soft score penalty) these fully remove/restrict candidates:
    # - hard_exclude_keywords: "ไม่กินของดิบเลย" (dietary restriction, not a
    #   medical allergy, so it doesn't belong in `allergens`) -> removed
    #   completely, same as an allergen.
    # - must_include_keywords: "กินแค่กุ้งกับปลา" (eat ONLY these) -> every
    #   other item is excluded, not just deprioritized.
    hard_exclude_keywords: List[str] = field(default_factory=list)
    must_include_keywords: List[str] = field(default_factory=list)
    min_items: int = 1
    max_items: int = 20

    # Group-dining fields. num_people is a second hard prerequisite (like
    # budget) before optimizing — a set built for 1 person and one built for
    # 4 are genuinely different problems, not just a bigger budget.
    num_people: Optional[int] = None
    # Tracks whether the agent has already asked the dislike/allergy question
    # this conversation, so it asks once (right after num_people is known)
    # instead of re-asking every turn even when the user has nothing to add.
    allergy_check_done: bool = False
    # Drinks and dessert are handled as a separate, deliberate step rather
    # than just more DP candidates: dessert is opt-in (None = not asked yet,
    # True/False once answered) and drinks are asked for by name, not
    # auto-picked, once num_people is known.
    wants_dessert: Optional[bool] = None
    drink_selection: List[str] = field(default_factory=list)
    dessert_selection: List[str] = field(default_factory=list)
    # Quantity is asked as its own step right after the drink/dessert NAME is
    # chosen — never silently assumed to equal num_people, even though that's
    # the likely default a user will give.
    drink_quantity: Optional[int] = None
    dessert_quantity: Optional[int] = None
    # "within" = drinks/dessert cost comes out of the stated budget (default);
    # "separate" = they're billed on top, food gets the full stated budget.
    # None = not asked yet.
    drinks_budget_mode: Optional[str] = None

    # Tracks which single field the agent's last question was about, so a
    # short next reply ("ไม่", "ไม่มี", "ค่ะ") can be interpreted in context
    # instead of the extractor guessing blind on an isolated one-line message.
    last_asked_field: Optional[str] = None

    last_result: Optional[Dict[str, Any]] = None
    conversation: List[Dict[str, str]] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Updating state from an LLM-extracted intent dict
    # ------------------------------------------------------------------
    def update_from_extraction(self, extracted: Dict[str, Any]) -> None:
        """Merge newly extracted fields into the running state.

        `allergens` are safety-critical, so they are only ever *added to*,
        never silently replaced or removed by a later extraction. Every
        other field can be overwritten when the user provides a new value.
        """
        if not extracted:
            return

        budget = extracted.get("budget")
        if budget is not None:
            try:
                budget_val = float(budget)
                if budget_val > 0:
                    self.budget = budget_val
            except (TypeError, ValueError):
                pass
        else:
            # No absolute number given — check for a relative change instead
            # ("เพิ่มงบอีก 100 บาท"), so "increase/decrease the budget" phrasing
            # actually takes effect instead of silently keeping the old value.
            delta = extracted.get("budget_delta")
            if delta is not None and self.budget is not None:
                try:
                    new_budget = self.budget + float(delta)
                    if new_budget > 0:
                        self.budget = new_budget
                except (TypeError, ValueError):
                    pass

        new_allergens = extracted.get("allergens") or []
        for tag in new_allergens:
            tag = str(tag).strip().lower()
            if tag and tag in KNOWN_ALLERGENS and tag not in self.allergens:
                self.allergens.append(tag)

        new_dislikes = extracted.get("dislikes") or []
        for kw in new_dislikes:
            kw = str(kw).strip()
            if kw and kw not in self.dislikes:
                self.dislikes.append(kw)

        new_prefs = extracted.get("preferred_keywords") or []
        for kw in new_prefs:
            kw = str(kw).strip()
            if kw and kw not in self.preferred_keywords:
                self.preferred_keywords.append(kw)

        new_hard_excludes = extracted.get("hard_exclude_keywords") or []
        for kw in new_hard_excludes:
            kw = str(kw).strip()
            if kw and kw not in self.hard_exclude_keywords:
                self.hard_exclude_keywords.append(kw)

        # must_include is a full restriction that replaces the previous one
        # (not accumulated) — "เอาแค่กุ้ง" then "เอาแค่ปลา" means "only fish"
        # now, not "fish AND shrimp" — unless the user's new list clearly
        # extends it, which the LLM already handles by re-listing everything
        # it currently means; we just take the latest non-empty extraction.
        new_must_include = extracted.get("must_include_keywords") or []
        if new_must_include:
            self.must_include_keywords = [str(kw).strip() for kw in new_must_include if str(kw).strip()]

        if extracted.get("num_people") is not None:
            try:
                people = int(extracted["num_people"])
                if people > 0:
                    self.num_people = people
            except (TypeError, ValueError):
                pass

        if extracted.get("allergy_check_answered") is True:
            self.allergy_check_done = True

        if extracted.get("wants_dessert") is not None:
            self.wants_dessert = bool(extracted["wants_dessert"])

        new_drinks = extracted.get("drink_selection") or []
        for kw in new_drinks:
            kw = str(kw).strip()
            if kw and kw not in self.drink_selection:
                self.drink_selection.append(kw)

        new_desserts = extracted.get("dessert_selection") or []
        for kw in new_desserts:
            kw = str(kw).strip()
            if kw and kw not in self.dessert_selection:
                self.dessert_selection.append(kw)

        mode = extracted.get("drinks_budget_mode")
        if mode in ("within", "separate"):
            self.drinks_budget_mode = mode

        if extracted.get("drink_quantity") is not None:
            try:
                qty = int(extracted["drink_quantity"])
                if qty > 0:
                    self.drink_quantity = qty
            except (TypeError, ValueError):
                pass

        if extracted.get("dessert_quantity") is not None:
            try:
                qty = int(extracted["dessert_quantity"])
                if qty > 0:
                    self.dessert_quantity = qty
            except (TypeError, ValueError):
                pass

        if extracted.get("min_items") is not None:
            try:
                self.min_items = max(1, int(extracted["min_items"]))
            except (TypeError, ValueError):
                pass

        if extracted.get("max_items") is not None:
            try:
                self.max_items = max(self.min_items, int(extracted["max_items"]))
            except (TypeError, ValueError):
                pass

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    def is_ready_to_optimize(self) -> bool:
        """Budget AND number of diners are both required — a set built for
        1 person and one built for 4 are genuinely different problems."""
        return self.budget is not None and self.budget > 0 and self.num_people is not None

    def needs_num_people(self) -> bool:
        """Budget is known but headcount isn't — ask before anything else."""
        return self.budget is not None and self.budget > 0 and self.num_people is None

    def needs_allergy_check(self) -> bool:
        """Ask the dislike/allergy question exactly once, right after
        headcount is known, instead of never asking or re-asking every turn.
        """
        return self.num_people is not None and not self.allergy_check_done

    def needs_drink_selection(self) -> bool:
        """Drinks are asked for by name, not auto-picked, once ready to build."""
        return self.is_ready_to_optimize() and self.allergy_check_done and not self.drink_selection

    def needs_drink_quantity(self) -> bool:
        """Once the drink NAME is chosen, ask how many separately — never
        silently assume it equals num_people, even though that's the likely
        answer a user will give."""
        return (
            self.is_ready_to_optimize()
            and self.allergy_check_done
            and bool(self.drink_selection)
            and self.drink_quantity is None
        )

    def needs_drinks_budget_mode(self) -> bool:
        """Once drinks (name + quantity) are settled, ask whether their cost
        counts against the stated budget or is billed separately.
        """
        return (
            self.is_ready_to_optimize()
            and self.allergy_check_done
            and bool(self.drink_selection)
            and self.drink_quantity is not None
            and self.drinks_budget_mode is None
        )

    def needs_dessert_confirmation(self) -> bool:
        """Dessert is opt-in — ask once, after drinks are fully settled."""
        return (
            self.is_ready_to_optimize()
            and self.allergy_check_done
            and bool(self.drink_selection)
            and self.drink_quantity is not None
            and self.drinks_budget_mode is not None
            and self.wants_dessert is None
        )

    def needs_dessert_selection(self) -> bool:
        """Dessert was confirmed ("yes") but no specific item was named in
        that same reply — ask which one before asking quantity."""
        return (
            self.is_ready_to_optimize()
            and self.allergy_check_done
            and bool(self.drink_selection)
            and self.drink_quantity is not None
            and self.drinks_budget_mode is not None
            and self.wants_dessert is True
            and not self.dessert_selection
        )

    def needs_dessert_quantity(self) -> bool:
        """Once dessert is confirmed + named, ask how many separately, mirroring
        the drink quantity step."""
        return (
            self.is_ready_to_optimize()
            and self.allergy_check_done
            and bool(self.drink_selection)
            and self.drink_quantity is not None
            and self.drinks_budget_mode is not None
            and self.wants_dessert is True
            and bool(self.dessert_selection)
            and self.dessert_quantity is None
        )

    def to_summary(self) -> str:
        """Human-readable summary of the current state, for the UI sidebar."""
        lines = []
        lines.append(f"งบประมาณ: {self.budget:.0f} บาท" if self.budget else "งบประมาณ: ยังไม่ระบุ")
        lines.append(f"จำนวนคน: {self.num_people} คน" if self.num_people else "จำนวนคน: ยังไม่ระบุ")
        lines.append(f"แพ้อาหาร: {', '.join(self.allergens) if self.allergens else 'ไม่มี'}")
        lines.append(f"ไม่ชอบ: {', '.join(self.dislikes) if self.dislikes else 'ไม่มี'}")
        lines.append(f"ชื่นชอบ: {', '.join(self.preferred_keywords) if self.preferred_keywords else 'ไม่มี'}")
        lines.append(
            f"ห้ามเด็ดขาด (ไม่ใช่ allergen): {', '.join(self.hard_exclude_keywords) if self.hard_exclude_keywords else 'ไม่มี'}"
        )
        lines.append(
            f"เอาเฉพาะ: {', '.join(self.must_include_keywords) if self.must_include_keywords else 'ไม่จำกัด'}"
        )
        lines.append(f"จำนวนจาน: {self.min_items}-{self.max_items} จาน")
        dessert_status = "ยังไม่ถาม" if self.wants_dessert is None else ("รับ" if self.wants_dessert else "ไม่รับ")
        lines.append(f"ของหวาน: {dessert_status}")
        drink_qty_label = f"{self.drink_quantity} แก้ว" if self.drink_quantity else "ยังไม่ระบุจำนวน"
        lines.append(
            f"เครื่องดื่มที่เลือก: {', '.join(self.drink_selection) if self.drink_selection else 'ยังไม่ระบุ'} ({drink_qty_label})"
        )
        dessert_qty_label = f"{self.dessert_quantity} ชิ้น" if self.dessert_quantity else "ยังไม่ระบุจำนวน"
        if self.wants_dessert:
            lines.append(
                f"ของหวานที่เลือก: {', '.join(self.dessert_selection) if self.dessert_selection else 'ยังไม่ระบุ'} ({dessert_qty_label})"
            )
        mode_label = {"within": "รวมในงบ", "separate": "แยกจากงบ", None: "ยังไม่ถาม"}[self.drinks_budget_mode]
        lines.append(f"ค่าเครื่องดื่ม/ของหวาน: {mode_label}")
        return "\n".join(lines)

    def add_message(self, role: str, content: str) -> None:
        self.conversation.append({"role": role, "content": content})

    def reset(self) -> None:
        self.budget = None
        self.allergens = []
        self.dislikes = []
        self.preferred_keywords = []
        self.hard_exclude_keywords = []
        self.must_include_keywords = []
        self.min_items = 1
        self.max_items = 20
        self.num_people = None
        self.allergy_check_done = False
        self.wants_dessert = None
        self.drink_selection = []
        self.dessert_selection = []
        self.drink_quantity = None
        self.dessert_quantity = None
        self.drinks_budget_mode = None
        self.last_asked_field = None
        self.last_result = None
        self.conversation = []
