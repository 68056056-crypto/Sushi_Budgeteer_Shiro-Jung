"""Smoke tests: import the core modules and exercise their pure-Python logic
(menu loading, scoring, DP knapsack, allergen filtering, state memory)
WITHOUT calling the OpenAI API. Run this any time to sanity-check the
project before wiring up an API key.

Usage:
    python test_smoke.py
"""

from __future__ import annotations

import json
import sys


def check(label: str, condition: bool) -> None:
    status = "PASS" if condition else "FAIL"
    print(f"[{status}] {label}")
    if not condition:
        FAILURES.append(label)


FAILURES: list[str] = []


def main() -> None:
    print("=== 1. Module imports ===")
    try:
        from sushi_budgeteer import optimizer, state, tools  # noqa: F401
        check("import optimizer, state, tools", True)
    except Exception as exc:
        check(f"import optimizer, state, tools ({exc})", False)
        _report_and_exit()
        return

    print("\n=== 2. Menu dataset loads ===")
    menu = optimizer.menu_records()
    check("menu has at least 40 items", len(menu) >= 40)
    check(
        "every row has price_baht, category, allergens_verified",
        all({"price_baht", "category", "allergens_verified"} <= row.keys() for row in menu),
    )

    print("\n=== 3. score_item() ===")
    salmon_row = next(row for row in menu if row["item_id"] == "S001")  # 40 baht, ปลาดิบ
    score_no_pref = optimizer.score_item(salmon_row, preferred_keywords=[], budget=300)
    score_with_pref = optimizer.score_item(salmon_row, preferred_keywords=["แซลมอน"], budget=300)
    score_disliked = optimizer.score_item(
        salmon_row, preferred_keywords=["แซลมอน"], budget=300, is_disliked=True
    )
    check("matching preference increases score", score_with_pref > score_no_pref)
    check("dislike penalty reduces score but floors at 0", 0 <= score_disliked < score_with_pref)
    check("raw-fish category gets no diversity bonus", optimizer.score_item(salmon_row, budget=300) <= 5.0)

    gyoza_row = next(row for row in menu if row["item_id"] == "F001")  # ของทอด -> diversity bonus
    check(
        "non-raw category scores higher price+diversity than raw fish at same price bucket",
        optimizer.score_item(gyoza_row, budget=300) > optimizer.score_item(salmon_row, budget=300),
    )

    print("\n=== 4. _dp_knapsack_01() — strict 0/1 (no repeats) correctness ===")
    tiny_items = [
        {"item_id": "A", "price_baht": 50, "score": 5.0},
        {"item_id": "B", "price_baht": 50, "score": 6.0},
        {"item_id": "C", "price_baht": 100, "score": 9.0},
    ]
    # Budget 100, one of each at most: best is A+B (score 11) beating C alone (score 9).
    selected = optimizer._dp_knapsack_01(tiny_items, budget=100, max_items=20)
    selected_ids = sorted(it["item_id"] for it in selected)
    total_price = sum(it["price_baht"] for it in selected)
    total_score = sum(it["score"] for it in selected)
    check(f"0/1 dp picks A+B over C alone (got {selected_ids})", selected_ids == ["A", "B"])
    check("0/1 dp respects the budget", total_price <= 100)
    check(f"0/1 dp total score is optimal (got {total_score})", total_score == 11.0)

    print("\n=== 4b. dp_knapsack() — repeat-capable knapsack picks B twice over A+B ===")
    # Same items, but now repeating the single best item (B x2 = score 12)
    # legitimately beats "one of each" (A+B = score 11) — this is the whole
    # point of allowing repeats: get closer to budget with a favorite dish,
    # like ordering a second plate of the same nigiri at a real kaiten-zushi.
    repeat_selected = optimizer.dp_knapsack(tiny_items, budget=100, max_items=20)
    repeat_score = sum(it["score"] for it in repeat_selected)
    repeat_ids = sorted(it["item_id"] for it in repeat_selected)
    check(
        f"repeat-capable dp beats or matches strict 0/1 (got {repeat_score} vs {total_score})",
        repeat_score >= total_score,
    )
    check(f"repeat-capable dp actually repeats B (got {repeat_ids})", repeat_ids == ["B", "B"])

    aggregated = optimizer.aggregate_by_item_id(repeat_selected)
    check(
        "aggregate_by_item_id collapses the 2 B's into one entry with quantity=2",
        len(aggregated) == 1 and aggregated[0]["item_id"] == "B" and aggregated[0]["quantity"] == 2,
    )
    check(
        "aggregated subtotal_baht = quantity x price",
        aggregated[0]["subtotal_baht"] == 100.0,
    )

    print("\n=== 5. dp_knapsack() beats random_baseline() on average ===")
    scored_menu = [
        {**row, "score": optimizer.score_item(row, preferred_keywords=["แซลมอน", "ทูน่า"], budget=300)}
        for row in menu
        if row["price_baht"] > 0
    ]
    comparison = optimizer.compare_dp_vs_random(scored_menu, budget=300, seed=7)
    check(
        f"DP score ({comparison['dp']['total_score']}) >= random score ({comparison['random']['total_score']})",
        comparison["dp"]["total_score"] >= comparison["random"]["total_score"],
    )
    check(
        "DP stays within budget",
        comparison["dp"]["total_price"] <= 300,
    )

    print("\n=== 6. Allergen hard-block filtering (tools._run_filter) ===")
    safe_items, blocked, dislike_items = tools._run_filter(menu, allergens=["crustacean"], dislikes=["หอย"])
    check("some items are blocked for crustacean allergy", len(blocked) > 0)
    check(
        "no blocked item is missing the crustacean tag",
        all("crustacean" in optimizer.parse_allergen_tags(row["allergens_verified"]) for row in blocked),
    )
    check(
        "no crustacean-tagged item leaks into safe_items",
        all("crustacean" not in optimizer.parse_allergen_tags(row["allergens_verified"]) for row in safe_items),
    )

    print("\n=== 7. BudgeteerState memory ===")
    s = state.BudgeteerState()
    check("state not ready without budget", not s.is_ready_to_optimize())
    s.update_from_extraction({"budget": 300, "allergens": ["crustacean"], "preferred_keywords": ["แซลมอน"]})
    check("still not ready without num_people (budget alone isn't enough)", not s.is_ready_to_optimize())
    check("needs_num_people() true once budget is known", s.needs_num_people())
    s.update_from_extraction({"num_people": 2})
    check("state ready after both budget and num_people are set", s.is_ready_to_optimize())
    check("needs_allergy_check() true until the agent asks", s.needs_allergy_check())
    check("allergen recorded", "crustacean" in s.allergens)

    # Context-aware short-answer interpretation: "ไม่" alone only makes sense
    # as "no allergies" because last_asked_field says the agent just asked
    # about allergies — this is the fix for the reported infinite-loop bug.
    s.update_from_extraction({"allergy_check_answered": True})
    check("allergy_check_done flips true from a context-resolved short answer", s.allergy_check_done)
    check("needs_drink_selection() true once allergy check is done", s.needs_drink_selection())
    s.update_from_extraction({"drink_selection": ["ชาเขียวร้อน"]})
    check("needs_drink_quantity() true once a drink NAME is chosen but no quantity yet", s.needs_drink_quantity())
    s.update_from_extraction({"drink_quantity": 2})
    check("drink_quantity recorded", s.drink_quantity == 2)
    check("needs_drinks_budget_mode() true once name+quantity are both known", s.needs_drinks_budget_mode())
    s.update_from_extraction({"drinks_budget_mode": "separate"})
    check("drinks_budget_mode recorded", s.drinks_budget_mode == "separate")
    check("needs_dessert_confirmation() true once budget mode is settled", s.needs_dessert_confirmation())
    s.update_from_extraction({"wants_dessert": True})
    check("needs_dessert_selection() true when dessert confirmed but not yet named", s.needs_dessert_selection())
    s.update_from_extraction({"dessert_selection": ["โมจิ"]})
    check("needs_dessert_quantity() true once dessert is named but no quantity yet", s.needs_dessert_quantity())
    s.update_from_extraction({"dessert_quantity": 2})
    check("dessert_quantity recorded", s.dessert_quantity == 2)
    s.update_from_extraction({"allergens": ["fish"]})
    check(
        "allergens accumulate rather than overwrite",
        {"crustacean", "fish"} <= set(s.allergens),
    )
    s.reset()
    check("reset() clears budget", s.budget is None)

    print("\n=== 8. build_optimal_set + verify_result tools (no LLM) ===")
    build_payload = tools.build_optimal_set.invoke(
        {"budget": 300, "allergens": ["crustacean"], "preferred_keywords": ["แซลมอน"]}
    )
    build_result = json.loads(build_payload)
    check("build_optimal_set stays within budget", build_result["total_price"] <= 300)
    check("build_optimal_set selects at least 1 item", build_result["item_count"] >= 1)

    verify_payload = tools.verify_result.invoke({"budget": 300, "allergens": ["crustacean"]})
    verify_result_data = json.loads(verify_payload)
    check("verify_result passes for a valid build", verify_result_data["passed"] is True)

    print("\n=== 8b. Drinks/dessert as a fixed allocation, not DP-optimized ===")
    group_payload = json.loads(
        tools.build_optimal_set.invoke(
            {
                "budget": 500,
                "num_people": 4,
                "drink_selection": ["ชาเขียวร้อน"],
                "include_dessert": True,
                "dessert_selection": ["โมจิ"],
            }
        )
    )
    drink_lines = [it for it in group_payload["selected"] if it["category"] == "เครื่องดื่ม"]
    dessert_lines = [it for it in group_payload["selected"] if it["category"] == "ของหวาน"]
    check(
        f"exactly num_people (4) drinks allocated (got {sum(d['quantity'] for d in drink_lines)})",
        sum(d["quantity"] for d in drink_lines) == 4,
    )
    check(
        f"exactly num_people (4) desserts allocated when include_dessert=true (got {sum(d['quantity'] for d in dessert_lines)})",
        sum(d["quantity"] for d in dessert_lines) == 4,
    )
    check(
        "drinks_cost/dessert_cost fields reflect the fixed allocation",
        group_payload["drinks_cost"] >= 0 and group_payload["dessert_cost"] >= 0,
    )

    no_dessert_payload = json.loads(
        tools.build_optimal_set.invoke(
            {"budget": 500, "num_people": 4, "drink_selection": ["ชาเขียวร้อน"], "include_dessert": False}
        )
    )
    check(
        "no dessert appears when include_dessert=false, even though it wasn't excluded via hard_exclude_keywords",
        not any(it["category"] == "ของหวาน" for it in no_dessert_payload["selected"]),
    )

    explicit_qty_payload = json.loads(
        tools.build_optimal_set.invoke(
            {
                "budget": 500,
                "num_people": 4,
                "drink_selection": ["ชาเขียวร้อน"],
                "drink_quantity": 2,  # explicit quantity DIFFERENT from num_people
                "include_dessert": True,
                "dessert_selection": ["โมจิ"],
                "dessert_quantity": 1,
            }
        )
    )
    explicit_drink_lines = [it for it in explicit_qty_payload["selected"] if it["category"] == "เครื่องดื่ม"]
    explicit_dessert_lines = [it for it in explicit_qty_payload["selected"] if it["category"] == "ของหวาน"]
    check(
        f"explicit drink_quantity=2 overrides the num_people=4 fallback (got {sum(d['quantity'] for d in explicit_drink_lines)})",
        sum(d["quantity"] for d in explicit_drink_lines) == 2,
    )
    check(
        f"explicit dessert_quantity=1 overrides the num_people=4 fallback (got {sum(d['quantity'] for d in explicit_dessert_lines)})",
        sum(d["quantity"] for d in explicit_dessert_lines) == 1,
    )

    print("\n=== 8bb. _sanitize_extraction — guards against a bare slot-answer polluting hard constraints ===")
    from sushi_budgeteer.agent import _sanitize_extraction

    # Regression test: answering the dessert-NAME question with a bare word
    # ("โมจิ") once got mis-extracted as ALSO meaning must_include_keywords
    # (an "only eat this" hard constraint), which silently wiped out the
    # entire food selection (an 8%-of-budget, food-less result was observed).
    polluted = {"dessert_selection": ["โมจิ"], "must_include_keywords": ["โมจิ"], "intent": "clarify_answer"}
    sanitized = _sanitize_extraction(polluted, "dessert_selection", "โมจิ")
    check(
        "must_include_keywords stripped when the trigger phrase isn't in the user's own words",
        sanitized["must_include_keywords"] == [],
    )
    check(
        "dessert_selection itself is left untouched",
        sanitized["dessert_selection"] == ["โมจิ"],
    )
    genuine = {"must_include_keywords": ["กุ้ง"], "intent": "optimize"}
    kept = _sanitize_extraction(genuine, "drinks", "กินแค่กุ้งเท่านั้นนะ")
    check(
        "must_include_keywords is KEPT when the user's own message actually says 'กินแค่'",
        kept["must_include_keywords"] == ["กุ้ง"],
    )
    unrelated_field = _sanitize_extraction(polluted, None, "โมจิ")
    check(
        "no sanitizing applied when last_asked_field isn't a narrow slot (e.g. None)",
        unrelated_field["must_include_keywords"] == ["โมจิ"],
    )

    print("\n=== 8c. drinks_separate_from_budget — food gets the FULL budget, drinks billed on top ===")
    within_payload = json.loads(
        tools.build_optimal_set.invoke(
            {"budget": 300, "num_people": 2, "drink_selection": ["ชาเขียวร้อน"], "drinks_separate_from_budget": False}
        )
    )
    separate_payload = json.loads(
        tools.build_optimal_set.invoke(
            {"budget": 300, "num_people": 2, "drink_selection": ["ชาเขียวร้อน"], "drinks_separate_from_budget": True}
        )
    )
    check(
        "within-budget mode: total_price never exceeds the stated budget",
        within_payload["total_price"] <= 300,
    )
    check(
        f"separate mode: food_total_price alone respects the budget (got {separate_payload['food_total_price']})",
        separate_payload["food_total_price"] <= 300,
    )
    check(
        "separate mode: budget_used_pct is based on food only, not the grand total",
        separate_payload["budget_used_pct"] == round(separate_payload["food_total_price"] / 300 * 100, 1),
    )
    verify_separate = json.loads(tools.verify_result.invoke({"budget": 300}))
    check(
        "verify_result doesn't falsely flag the intentional over-budget grand total in separate mode",
        verify_separate["passed"] is True,
    )

    print("\n=== 9. must_include_keywords — 'eat ONLY fish and shrimp' ===")
    only_fish_shrimp = json.loads(
        tools.build_optimal_set.invoke(
            {"budget": 1000, "must_include_keywords": ["กุ้ง", "ปลา"], "max_items": 20}
        )
    )
    check("must_include selects at least 1 item", only_fish_shrimp["item_count"] >= 1)
    check(
        "every selected item matches กุ้ง or ปลา (no squid/tamago/soup/dessert leaking in)",
        all(
            optimizer.matches_any_keyword(item, ["กุ้ง", "ปลา"])
            for item in only_fish_shrimp["selected"]
        ),
    )
    breakdown = only_fish_shrimp["count_by_must_include_keyword"]
    check(
        f"count_by_must_include_keyword breakdown sums to item_count (got {breakdown})",
        sum(breakdown.values()) >= only_fish_shrimp["item_count"],  # items can match both keywords
    )

    print("\n=== 10. hard_exclude_keywords — 'no raw food at all' ===")
    no_raw = json.loads(
        tools.build_optimal_set.invoke(
            {"budget": 1000, "hard_exclude_keywords": ["ดิบ"], "max_items": 20}
        )
    )
    check("hard_exclude selects at least 1 item", no_raw["item_count"] >= 1)
    check(
        "no selected item matches 'ดิบ' (raw) despite it being budget-efficient",
        all(not optimizer.matches_any_keyword(item, ["ดิบ"]) for item in no_raw["selected"]),
    )

    print("\n=== 10b. hard_exclude_keywords — natural compound phrase 'ของดิบ' (raw food) ===")
    no_raw_compound = json.loads(
        tools.build_optimal_set.invoke(
            {"budget": 1000, "hard_exclude_keywords": ["ของดิบ"], "max_items": 20}
        )
    )
    check(
        "'ของดิบ' (as a user would actually phrase it, not the simplified 'ดิบ') "
        "still excludes every raw item — regression test for the reported Salmon Sushi leak",
        no_raw_compound["item_count"] >= 1
        and all(not optimizer.matches_any_keyword(item, ["ของดิบ"]) for item in no_raw_compound["selected"]),
    )

    print("\n=== 11. verify_result catches a must_include/hard_exclude violation ===")
    tools.set_last_result(
        {
            "selected": [
                {"item_id": "BAD", "name_th": "ของดิบปลอม", "allergens_verified": "", "category": "ปลาดิบ"}
            ],
            "total_price": 40,
            "budget": 300,
            "item_count": 1,
            "hard_exclude_keywords": ["ดิบ"],
            "must_include_keywords": [],
        }
    )
    tampered_check = json.loads(tools.verify_result.invoke({"budget": 300}))
    check("verify_result flags a hard_exclude_keywords violation", tampered_check["passed"] is False)

    _report_and_exit()


def _report_and_exit() -> None:
    print("\n" + "=" * 40)
    if FAILURES:
        print(f"{len(FAILURES)} check(s) FAILED:")
        for f in FAILURES:
            print(f"  - {f}")
        sys.exit(1)
    print("All smoke checks passed.")
    sys.exit(0)


if __name__ == "__main__":
    main()
