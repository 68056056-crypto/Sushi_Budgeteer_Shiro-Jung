"""Smoke test — ตรวจ import + logic หลักโดยไม่ต้องใช้ LLM"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "sushi_budgeteer"))
sys.path.insert(0, os.path.dirname(__file__))

# Test 1: optimizer
from optimizer import dp_knapsack, score_item, random_baseline, compare_dp_vs_random
print("optimizer: OK")

# Test 2: state
from state import BudgeteerState
s = BudgeteerState()
s.update_from_extraction({"budget": 300, "allergens": ["fish"], "preferences": ["salmon"]})
assert s.budget == 300, f"budget={s.budget}"
assert "fish" in s.allergens, f"allergens={s.allergens}"
assert s.is_ready_to_optimize()
print("state: OK")

# Test 3: tools — import + CSV load
from tools import _load_menu, _run_filter, AGENT_TOOLS
df = _load_menu()
assert len(df) > 0, "CSV empty"
print(f"tools: OK — {len(df)} menu items loaded")

# Test 4: filter — allergen hard block + dislike soft
result = _run_filter(allergens=["fish"], dislikes=["หมึก"], categories_wanted=None)
assert result["counts"]["allergen_blocked"] > 0, "No allergen block"
assert result["counts"]["safe"] > 0, "No safe items"
print(
    f"filter: OK — safe={result['counts']['safe']}, "
    f"blocked={result['counts']['allergen_blocked']}, "
    f"dislike={result['counts']['dislike']}"
)

# Test 5: DP end-to-end
import pandas as pd
safe_df = pd.DataFrame(result["safe_items"])
items_scored = []
for _, row in safe_df.iterrows():
    s_val = score_item(row=row, preferred_keywords=["กุ้ง"], budget=300, is_disliked=False)
    items_scored.append({**row.to_dict(), "score": s_val})

selected = dp_knapsack(items=items_scored, budget=300, max_items=10)
total = sum(i["price_baht"] for i in selected)
assert total <= 300, f"Budget exceeded: {total}"
assert len(selected) > 0, "DP returned empty"
print(f"dp_knapsack: OK — {len(selected)} items, total={total} baht")

# Test 6: random baseline
rand = random_baseline(items=items_scored, budget=300, seed=42)
assert rand["total_price"] <= 300, f"Random exceeded budget: {rand['total_price']}"
print(f"random_baseline: OK — {rand['item_count']} items, score={rand['total_score']}")

# Test 7: compare DP vs Random
comp = compare_dp_vs_random(items=items_scored, budget=300)
dp_score = comp["dp"]["total_score"]
rand_score = comp["random"]["total_score"]
print(
    f"compare: DP score={dp_score} vs Random score={rand_score} "
    f"(DP +{comp['improvement']['score_gain_pct']}%)"
)

# Test 8: verify_result logic (call the underlying function directly)
from tools import verify_result
verify_input = {
    "selected_items": [
        {"item_id": "S001", "name_th": "ซูชิแซลมอน", "price_baht": 40},
        {"item_id": "S005", "name_th": "ซูชิไข่หวาน", "price_baht": 40},
    ],
    "budget": 200,
    "allergens": [],
}
vr = verify_result.invoke(verify_input)
assert vr["passed"] is True, f"verify failed: {vr}"
assert vr["total_price"] == 80
print("verify_result: OK")

# Test 9: BudgeteerState remove allergen
s2 = BudgeteerState()
s2.update_from_extraction({"allergens": ["fish", "gluten"]})
assert "fish" in s2.allergens
s2.allergens.remove("fish")
assert "fish" not in s2.allergens
assert "gluten" in s2.allergens
print("state remove: OK")

print()
print("=" * 40)
print("All smoke tests PASSED!")
print("=" * 40)
