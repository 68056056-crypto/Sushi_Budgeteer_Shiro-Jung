"""Budget proximity without relaxing explicit quantities or dietary constraints."""
import itertools
import random
import unittest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import cents, budget_target_cents
from sushi_budgeteer.optimizer import _dp_knapsack_01, dp_knapsack
from sushi_budgeteer.presentation import render_menu
from sushi_budgeteer.service import MenuService


class BudgetObjectiveTest(unittest.TestCase):
    def test_budget_band_precedes_cheap_high_score(self):
        items=[{'item_id':'cheap','price_baht':40,'score':100},
               {'item_id':'premium','price_baht':100,'score':1}]
        actual=_dp_knapsack_01(items,100,max_items=1,objective='budget')
        self.assertEqual(actual[0]['item_id'],'premium')

    def test_preferences_still_win_inside_near_budget_band(self):
        items=[{'item_id':'preferred','price_baht':95,'score':10},
               {'item_id':'other','price_baht':100,'score':1}]
        actual=_dp_knapsack_01(items,100,max_items=1,objective='budget')
        self.assertEqual(actual[0]['item_id'],'preferred')

    def test_budget_objective_matches_exhaustive_search_in_satang(self):
        rng=random.Random(91)
        for _ in range(35):
            items=[{'item_id':str(i),'price_baht':rng.randint(1,500)/100,'score':rng.randint(0,10)} for i in range(7)]
            budget=rng.randint(20,1500)/100
            limit=rng.randint(1,4)
            minimum=rng.randint(1,limit)
            feasible=[subset for n in range(minimum,limit+1) for subset in itertools.combinations(items,n)
                      if sum(cents(x['price_baht']) for x in subset)<=cents(budget)]
            actual=_dp_knapsack_01(items,budget,max_items=limit,min_items=minimum,objective='budget')
            if not feasible:
                self.assertEqual(actual,[])
                continue
            spend=lambda subset:sum(cents(x['price_baht']) for x in subset)
            score=lambda subset:sum(x['score'] for x in subset)
            near=[subset for subset in feasible if spend(subset)*100>=cents(budget)*95]
            metric=(lambda subset:(score(subset),spend(subset))) if near else (lambda subset:(spend(subset),score(subset)))
            self.assertEqual(metric(actual),max(metric(subset) for subset in (near or feasible)))

    def test_diversity_reduces_repeats_without_mutating_scores(self):
        items=[{'item_id':name,'price_baht':40,'score':score} for name,score in [('a',5),('b',4),('c',3)]]
        plain=dp_knapsack(items,120,max_items=3,objective='budget')
        diverse=dp_knapsack(items,120,max_items=3,objective='budget',diversity=True)
        self.assertEqual(len({x['item_id'] for x in plain}),1)
        self.assertEqual(len({x['item_id'] for x in diverse}),3)
        self.assertEqual(items[0]['score'],5)

    def test_reserve_is_rounded_down_to_satang(self):
        self.assertEqual(budget_target_cents(3000.01,.8),240000)
        for ratio in (0,-1,1.1,float('nan'),float('inf')):
            with self.assertRaises(ValueError): budget_target_cents(3000,ratio)


class BudgetMealTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def test_3000_baht_two_options_reserve_20_percent_without_implicit_20_item_cap(self):
        model=ScriptedModel([],{'budget':3000,'num_people':2,'drink_selection':['ชาเขียวร้อน'],
                                'drink_quantity':2,'wants_dessert':False})
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        summary=agent.chat('งบ3000 2คน ชาเขียวร้อน2 ไม่รับของหวาน')
        self.assertIn('ไม่เกิน 60 รายการ',summary)
        answer=agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertEqual(len(agent.last_options),2)
        for option in agent.last_options:
            self.assertGreaterEqual(option['total_price'],2280)
            self.assertEqual(option['reserved_budget'],600)
            self.assertLessEqual(option['total_price'],2400)
            self.assertGreaterEqual(3000-option['total_price'],600)
            self.assertLessEqual(option['item_count'],60)
            self.assertTrue(option['policy_decision']['allow'])
            self.assertTrue(all(x['quantity']<=3 for x in option['selected'] if x['category'] not in {'เครื่องดื่ม','ของหวาน'}))
        self.assertIn('เหลือ',answer)
        self.assertIn('ใช้ ',answer)
        self.assertIn('สรุปรายการทั้งหมด',agent.select_option(1))
        self.assertEqual(agent.food_choice['result_id'],agent.last_options[1]['result_id'])

    def test_explicit_item_cap_survives_budget_increase(self):
        model=ScriptedModel([],{'budget':3000,'num_people':2,'max_items':20})
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        agent.chat('งบ3000 2คน ไม่เกิน20รายการ')
        answer=agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertTrue(agent.state.max_items_explicit)
        self.assertEqual(agent.item_limit(),20)
        self.assertTrue(agent.last_options)
        self.assertTrue(all(x['item_count']<=20 for x in agent.last_options))
        self.assertNotIn('ยังจัดให้ใกล้งบกว่านี้ไม่ได้',answer)
        self.assertEqual(agent.last_options[0]['constraints']['max_items'],20)
        self.assertIn('20 รายการ',answer)
        agent.state.update_from_extraction({'budget':4000})
        self.assertEqual(agent.item_limit(),20)
        agent.reset_order()
        self.assertFalse(agent.state.max_items_explicit)

    def test_fixed_drinks_reserved_within_budget(self):
        service=MenuService()
        built=service.build(budget=500,max_items=60,drink_selection=['ชาเขียวมัทฉะลาเต้เย็น'],drink_quantity=2,spend_ratio=.8)
        # Use catalog-supported selection (substring matches the actual drink name).
        self.assertEqual(built['status'],'candidate')
        result=built['result']
        self.assertLessEqual(result['total_price'],400)
        self.assertGreaterEqual(result['total_price'],380)
        self.assertTrue(service.verify(built['result_id'])['passed'])

    def test_separate_drinks_budget_utilization_uses_food_only(self):
        service=MenuService()
        built=service.build(budget=300,max_items=60,drink_selection=['น้ำเปล่า'],drink_quantity=2,
                            drinks_separate_from_budget=True)
        self.assertEqual(built['status'],'candidate')
        result=built['result']
        self.assertGreaterEqual(result['food_total_price'],285)
        self.assertLessEqual(result['food_total_price'],300)
        self.assertEqual(result['total_price'],result['food_total_price']+40)
        rendered=render_menu(result)
        self.assertIn('คิดเพิ่มนอกงบ',rendered)
        self.assertIn(f"ใช้ {result['food_total_price']:,.2f} บาท",rendered)
        self.assertNotIn("%",rendered)

    def test_reserve_limit_is_rechecked_before_release(self):
        service=MenuService()
        built=service.build(budget=300,max_items=60)
        result=service.results[built['result_id']]
        self.assertGreater(result['total_price'],240)
        result['constraints']['spend_ratio']=.8
        checked=service.verify(built['result_id'])
        self.assertFalse(checked['passed'])
        self.assertTrue(any('งบสำรอง' in issue for issue in checked['issues']))

    def test_displayed_reserve_is_verified_and_not_just_a_label(self):
        service=MenuService()
        built=service.build(budget=300,spend_ratio=.8)
        service.results[built['result_id']]['reserved_budget']=200
        checked=service.verify(built['result_id'])
        self.assertFalse(checked['passed'])
        self.assertTrue(any('งบสำรอง' in issue for issue in checked['issues']))


if __name__=='__main__':
    unittest.main()
