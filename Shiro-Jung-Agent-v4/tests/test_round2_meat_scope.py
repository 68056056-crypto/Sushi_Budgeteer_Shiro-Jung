"""Round-2 consumer meat clarification and independent hard/allergy enforcement."""
import os
import unittest
from unittest.mock import patch
from streamlit.testing.v1 import AppTest
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import ROOT, records
from sushi_budgeteer.dietary import hard_excluded, ingredient_allergens, requested_tags, soft_disliked
from sushi_budgeteer.meat_scope import meat_relation
from sushi_budgeteer.tools import _run_filter
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.opa import evaluate


class MeatScopeTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def ready(self, phrase, field, guessed):
        model=ScriptedModel([],{'budget':1000,'num_people':2,'preferred_keywords':['แซลมอน'],field:guessed})
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        answer=agent.chat('1000 บาท 2 คน ชอบแซลมอน '+phrase)
        return agent,answer

    def test_generic_relations_do_not_capture_specific_meat_or_negated_allergy(self):
        for text,expected in [('ไม่กินเนื้อ','hard_exclude_keywords'),('ไม่ชอบเนื้อเลย','dislikes'),
                              ('แพ้เนื้อ และนม','allergens')]:
            self.assertEqual(meat_relation(text),expected)
        for text in ('ไม่กินเนื้อวัว','ไม่ชอบเนื้อหมู','ไม่แพ้เนื้อ','ไม่ได้แพ้เนื้อ'):
            self.assertIsNone(meat_relation(text),text)

    def test_land_meat_hard_alias_filters_real_pork_and_chicken_not_fish(self):
        safe,blocked,_=_run_filter(records(),hard_exclude_keywords=['เนื้อ'])
        self.assertTrue({'F001','F002'} <= {row['item_id'] for row in blocked})
        self.assertIn('S001',{row['item_id'] for row in safe})
        self.assertEqual(requested_tags(['เนื้อ']),['beef','chicken','pork'])
        self.assertTrue(hard_excluded({'dietary_tags':'beef','dietary_status':'reviewed_dataset'},['เนื้อวัว']))
        self.assertFalse(hard_excluded({'dietary_tags':'fish','dietary_status':'reviewed_dataset'},['เนื้อวัว']))

    def test_hard_choice_preserves_meal_and_never_guesses_beef(self):
        agent,answer=self.ready('ไม่กินเนื้อ','hard_exclude_keywords',['เนื้อวัว'])
        self.assertEqual(agent.state.hard_exclude_keywords,[])
        self.assertEqual(agent.pending_meat_scope,'hard_exclude_keywords')
        self.assertIn('ปลาและอาหารทะเลยังเลือกได้',answer)
        self.assertFalse(agent.last_options)
        agent._confirm_order()
        self.assertFalse(agent.last_options)
        agent.chat('หมู')
        self.assertEqual(agent.state.hard_exclude_keywords,['หมู'])
        self.assertEqual(agent.state.allergens,[])
        self.assertEqual(agent.state.budget,1000)
        self.assertEqual(agent.state.num_people,2)
        self.assertEqual(agent.state.preferred_keywords,['แซลมอน'])
        self.assertTrue(agent.pending_confirmation)
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertTrue(agent.last_options)
        self.assertTrue(all('F001' not in {row['item_id'] for row in option['selected']} for option in agent.last_options))

    def test_dislike_choice_is_soft_and_uses_meat_tags(self):
        agent,_=self.ready('ไม่ชอบเนื้อ','dislikes',['เนื้อวัว'])
        agent.chat('หมู')
        self.assertEqual(agent.state.dislikes,['หมู'])
        self.assertEqual(agent.state.allergens,[])
        self.assertEqual(agent.state.hard_exclude_keywords,[])
        safe,blocked,disliked=_run_filter(records(),dislikes=agent.state.dislikes)
        self.assertIn('F001',{row['item_id'] for row in safe})
        self.assertIn('F001',{row['item_id'] for row in disliked})
        self.assertFalse(blocked)
        self.assertFalse(soft_disliked(next(row for row in records() if row['item_id']=='S004'),['หมู']))

    def test_allergy_choice_blocks_real_chicken_even_in_simulation(self):
        agent,_=self.ready('แพ้เนื้อ','allergens',['beef'])
        agent.chat('ไก่')
        self.assertEqual(agent.state.allergens,['chicken'])
        self.assertEqual(agent.state.hard_exclude_keywords,[])
        agent.chat('ยืนยันข้อมูลและจัดชุด')
        self.assertFalse(agent.last_options)
        self.assertTrue(agent.allergy_simulation_available)
        agent.chat('ดูชุดจำลองจากข้อมูลเมนู')
        self.assertTrue(agent.last_options)
        menu={row['item_id']:row for row in records()}
        for option in agent.last_options:
            for row in option['selected']:
                self.assertNotIn('chicken',ingredient_allergens(menu[row['item_id']]))
        self.assertTrue(all(row['allergen_status']=='unknown' for row in menu.values()))

    def test_all_land_meats_choice_does_not_add_fish_allergy_and_reset_clears_question(self):
        agent,_=self.ready('แพ้เนื้อ','allergens',['beef'])
        agent.chat('สัตว์บกทั้งหมด')
        self.assertEqual(set(agent.state.allergens),{'pork','beef','chicken'})
        agent.reset_order()
        self.assertIsNone(agent.pending_meat_scope)
        self.assertEqual(agent.state.allergens,[])

    def test_opa_rejects_raw_chicken_conflict_even_with_false_python_flags(self):
        service=MenuService();built=service.build(budget=300)
        facts=service.verify(built['result_id'])['policy_input']
        facts.update(user_allergens=['chicken'],data_mode='simulation',python_issues=[])
        facts['lines'][0].update(allergen_tags=[],dietary_tags=['chicken'],allergen_blocked=False)
        self.assertIn('allergen_conflict',evaluate(facts)['deny_reasons'])

    def test_meat_change_after_food_selection_uses_same_meal(self):
        model=ScriptedModel([],{'budget':1000,'num_people':2,'preferred_keywords':['แซลมอน']})
        agent=BudgeteerAgent(llm=model,consumer_flow=True)
        agent.chat('1000 บาท 2คน ชอบแซลมอน')
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        agent.select_option(0)
        model.extraction={'hard_exclude_keywords':['เนื้อวัว']}
        agent.chat('ไม่กินเนื้อ')
        self.assertEqual(agent.pending_meat_scope,'hard_exclude_keywords')
        agent.chat('สัตว์บกทั้งหมด')
        self.assertEqual(agent.state.budget,1000)
        self.assertEqual(agent.state.preferred_keywords,['แซลมอน'])
        agent.chat('ยืนยันว่าไม่แพ้และจัดชุด')
        self.assertTrue(agent.last_options)
        self.assertTrue(all(not ({'F001','F002'} & {row['item_id'] for row in option['selected']}) for option in agent.last_options))

    def test_meat_allergy_choice_preserves_other_allergies(self):
        agent=BudgeteerAgent(llm=ScriptedModel([],{'budget':1000,'num_people':2,'allergens':['beef']}),consumer_flow=True)
        agent.state.allergens=['fish']
        agent.chat('1000 บาท 2คน แพ้เนื้อ')
        agent.chat('ไก่')
        self.assertEqual(set(agent.state.allergens),{'fish','chicken'})
        self.assertEqual(agent.state.budget,1000)

    def test_ui_meat_choice_does_not_repeat_budget_or_people(self):
        agent,answer=self.ready('ไม่กินเนื้อ','hard_exclude_keywords',['เนื้อวัว'])
        with patch.dict(os.environ,{'OPENAI_API_KEY':'meat-ui-placeholder'}):
            page=AppTest.from_file(str(ROOT/'app.py'))
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('meat-ui-placeholder','gpt-4o-mini','strict')
            page.session_state['chat_history']=[{'role':'assistant','content':answer}]
            page.run()
            page.button(key='meat_สัตว์บกทั้งหมด').click().run()
            self.assertFalse(page.exception)
            self.assertEqual(set(agent.state.hard_exclude_keywords),{'หมู','เนื้อวัว','ไก่'})
            self.assertEqual(agent.state.budget,1000)
            self.assertEqual(agent.state.num_people,2)
            self.assertTrue(agent.pending_confirmation)
            self.assertIsNone(agent.pending_meat_scope)


if __name__=='__main__':unittest.main()
