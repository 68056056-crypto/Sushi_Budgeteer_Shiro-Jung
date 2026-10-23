"""Exact requested-menu identity and catalogue-wide structured intake failures."""
import unittest
from unittest.mock import AsyncMock,patch
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.menu_matching import exact_match,suggest
from sushi_budgeteer.database import records
from sushi_budgeteer.extra_order import unavailable_order_names

class ExactIntakeTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def agent(self,extraction=None):
        return BudgeteerAgent(llm=ScriptedModel([],extraction or {}),consumer_flow=True)

    def test_otoro_never_matches_negitoro(self):
        rows=records();otoro=next(row for row in rows if row['item_id']=='S015')
        negi=next(row for row in rows if row['item_id']=='R005')
        self.assertTrue(exact_match(otoro,'โอโทโร่'))
        self.assertFalse(exact_match(negi,'โอโทโร่'))
        built=MenuService().build(budget=1000,required_keywords=['โอโทโร่'],max_items=8,max_items_explicit=True)
        self.assertEqual(built['status'],'candidate')
        self.assertIn('S015',{row['item_id'] for row in built['result']['selected']})
        excluded=MenuService().build(budget=1000,required_keywords=['โอโทโร่'],excluded_item_ids=['S015'])
        self.assertEqual(excluded['status'],'requires_clarification')

    def test_typo_requires_explicit_user_choice_and_keeps_allergies(self):
        agent=self.agent({'budget':1000,'num_people':2,'preferred_keywords':['โอโทร่'],'allergens':['milk']})
        with patch.object(agent,'_run',new_callable=AsyncMock) as run:
            response=agent.chat('งบ1000บาท 2คน แพ้นม อยากกินโอโทร่ ขอใส่ในชุดด้วย')
            run.assert_not_awaited()
        self.assertIn('ไม่มี โอโทร่ ในเมนู',response)
        self.assertIn('ซูชิโอโทโร่',response)
        self.assertFalse(agent.pending_confirmation)
        self.assertEqual(agent.state.required_keywords,['โอโทร่'])
        agent.chat('ซูชิโอโทโร่')
        self.assertEqual(agent.state.required_keywords,['ซูชิโอโทโร่'])
        self.assertEqual(agent.state.allergens,['milk'])
        self.assertTrue(agent.pending_confirmation)

    def test_unknown_requested_item_is_preserved_not_silently_dropped(self):
        agent=self.agent({'budget':1000,'num_people':2,'preferred_keywords':['พิซซ่า']})
        answer=agent.chat('งบ1000บาท 2คน ต้องมีพิซซ่าในชุดด้วย')
        self.assertIn('ไม่มี พิซซ่า ในเมนู',answer)
        self.assertIn('พิซซ่า',agent.state.required_keywords)
        self.assertFalse(agent.last_options)

    def test_expensive_required_menu_names_price_and_asks_budget(self):
        agent=self.agent({'budget':100,'num_people':1,'required_keywords':['โอโทโร่']})
        response=agent.chat('งบ100บาท 1คน ต้องมีโอโทโร่')
        self.assertIn('120.00',response)
        self.assertIn('150.00',response)
        self.assertIn('เพิ่มงบ',response)
        self.assertEqual(agent.state.budget,100)
        self.assertFalse(agent.pending_confirmation)
        response=agent.chat('150')
        self.assertEqual(agent.state.budget,150)
        self.assertTrue(agent.pending_confirmation)

    def test_service_does_not_hide_price_in_generic_failure(self):
        built=MenuService().build(budget=100,spend_ratio=.8,required_keywords=['โอโทโร่'])
        self.assertEqual(built['status'],'requires_clarification')
        answer=self.agent()._friendly_issues(built['issues'])
        self.assertIn('120.00',answer)
        self.assertIn('เพิ่มงบ',answer)

    def test_nonpositive_extracted_budget_all_phrasings_preserve_valid_fields(self):
        for text,budget in [('งบศูนย์บาท',0),('มีเงิน 0.00 บาท',0.0),('budget=-5',-5),('ติดลบหนึ่งบาท',-1)]:
            with self.subTest(text=text):
                agent=self.agent({'budget':budget,'num_people':2,'allergens':['milk']})
                with patch.object(agent,'_run',new_callable=AsyncMock) as run:
                    response=agent.chat(text+' 2คน แพ้นม')
                    run.assert_not_awaited()
                self.assertIn('งบต้องมากกว่า 0',response)
                self.assertNotIn('อ่านความต้องการไม่สำเร็จ',response)
                self.assertIsNone(agent.state.budget)
                self.assertEqual(agent.state.num_people,2)
                self.assertEqual(agent.state.allergens,['milk'])
                self.assertFalse(agent.pending_confirmation)

    def test_signed_contextual_budget_validation_without_model(self):
        agent=self.agent();agent.state.num_people=1;agent.state.last_asked_field='budget'
        for text in ('-10','0','0.00','-0.5'):
            with patch.object(agent.llm,'invoke',side_effect=AssertionError('no extraction call')):
                self.assertIn('มากกว่า 0',agent.chat(text))
        self.assertEqual(agent.state.last_asked_field,'budget')

    def test_all_unknown_extra_names_are_reported_atomically(self):
        for text,name in [('เบียร์ 1','เบียร์'),('แฟนต้า2','แฟนต้า'),('บราวนี่ 3','บราวนี่'),('กาแฟดำ1','กาแฟดำ')]:
            self.assertEqual(unavailable_order_names(text,records()),[name])
            agent=self.agent();agent.last_options=[{'total_price':500}]
            self.assertIn('ไม่มี '+name+' ในเมนู',agent.chat(text))
            self.assertEqual(agent.last_options,[{'total_price':500}])
        agent=self.agent();agent.extras_plan={'B005':1}
        self.assertIn('แฟนต้า',agent.chat('น้ำส้ม2 แฟนต้า1'))
        self.assertEqual(agent.extras_plan,{'B005':1})
        self.assertEqual(unavailable_order_names('งบ1000บาท2คน',records()),[])
        self.assertEqual(unavailable_order_names('น้ำส้ม2ชาเขียว1',records()),[])
        for name in ('แฟนต้า','บราวนี่'):
            self.assertEqual(unavailable_order_names(name,records(),category='ของหวาน',allow_name_only=True),[name])

    def test_unknown_structured_dessert_is_reported_and_keeps_intake(self):
        agent=self.agent({'budget':1000,'num_people':2,'wants_dessert':True,'dessert_selection':['บราวนี่']})
        response=agent.chat('งบ1000บาท 2คน รับบราวนี่ด้วย')
        self.assertIn('ไม่มี บราวนี่ ในเมนู',response)
        self.assertEqual(agent.state.budget,1000)
        self.assertEqual(agent.state.num_people,2)
        self.assertFalse(agent.state.dessert_selection)

    def test_fuzzy_candidates_are_not_a_resolution(self):
        rows=suggest('โอโทร่',records())
        self.assertIn('S015',{row['item_id'] for row in rows})
        self.assertFalse(any(exact_match(row,'โอโทร่') for row in records()))

    def test_live_harness_checks_new_budget_case_and_exact_dish_offline(self):
        import json,os,sys
        from pathlib import Path
        from scripts import live_sessions
        source=Path(self.tmp.name)/'cases.json';output=Path(self.tmp.name)/'report.json'
        scenarios=[{'id':'invalid','mode':'strict','turns':[{'message':'งบศูนย์บาท 2คน','expected':'budget_invalid','budget':None,'num_people':2}]},
                   {'id':'exact','mode':'strict','turns':[{'message':'งบ1000บาท 2คน ต้องมีโอโทโร่','expected':'recommendation','budget':1000,'required_keywords':['โอโทโร่'],'required_item_ids':['S015']}]}]
        source.write_text(json.dumps(scenarios,ensure_ascii=False))
        extractions=iter([{'budget':0,'num_people':2},{'budget':1000,'num_people':2,'required_keywords':['โอโทโร่']}])
        def factory(**kwargs):
            return BudgeteerAgent(llm=ScriptedModel([],next(extractions)),**kwargs)
        with patch.dict(os.environ,{'OPENAI_API_KEY':'fixture-only'}),patch.object(live_sessions,'BudgeteerAgent',side_effect=factory),patch.object(sys,'argv',['live_sessions','--scenarios',str(source),'--output',str(output)]):
            self.assertEqual(live_sessions.main(),0)
        result=json.loads(output.read_text())
        self.assertEqual(result['success_rate'],1)
        self.assertFalse(result['live_llm_tested'])
        self.assertEqual(result['model_selected_recommendations'],0)
