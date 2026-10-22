"""Consumer review regressions: actual requests must survive scoring and dialogue."""
import copy
import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import test_system as fixtures
from test_system import ScriptedModel
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.optimizer import dp_knapsack,score_item,matches_any_keyword
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.presentation import render_menu
from sushi_budgeteer.persistence import SessionStore

class RequestedMealTest(unittest.TestCase):
    setUp=fixtures.CatalogTest.setUp
    tearDown=fixtures.CatalogTest.tearDown

    def agent(self,extraction=None):
        return BudgeteerAgent(llm=ScriptedModel([],extraction or {}),consumer_flow=True)

    def test_required_coverage_matches_exhaustive_optimum(self):
        import itertools
        items=[dict(item_id='a',name_th='โอโทโร่',price_baht=80,score=1),
               dict(item_id='b',name_th='ซุปไข่',price_baht=40,score=5),
               dict(item_id='c',name_th='ปลา',price_baht=70,score=4)]
        actual=dp_knapsack(items,160,max_items=3,max_repeat_per_item=1,required_keywords=['โอโทโร่'])
        valid=[s for count in range(4) for s in itertools.combinations(items,count)
               if sum(x['price_baht'] for x in s)<=160 and any(x['item_id']=='a' for x in s)]
        best=max((sum(x['score'] for x in s),sum(x['price_baht'] for x in s)) for s in valid)
        self.assertEqual((sum(x['score'] for x in actual),sum(x['price_baht'] for x in actual)),best)
        self.assertEqual(dp_knapsack(items,10,required_keywords=['โอโทโร่']),[])
        both=dp_knapsack(items,160,max_items=3,max_repeat_per_item=1,required_keywords=['โอโทโร่','ซุปไข่'])
        self.assertTrue({'a','b'}.issubset({x['item_id'] for x in both}))

    def test_explicit_request_not_only_filter_and_survives_alternative(self):
        agent=self.agent({'preferred_keywords':['โอโทโร่'],'must_include_keywords':['โอโทโร่']})
        agent.chat('งบ1000บาท 2คน อยากกินโอโทโร่ ขอใส่ในชุดด้วย')
        self.assertIn('โอโทโร่',agent.state.required_keywords)
        self.assertFalse(agent.state.must_include_keywords)
        service=MenuService()
        built=service.build(budget=1000,max_items=8,max_items_explicit=True,
                            preferred_keywords=['โอโทโร่'],required_keywords=['โอโทโร่'])
        self.assertEqual(built['status'],'candidate',built)
        self.assertTrue(any(matches_any_keyword(x,['โอโทโร่']) for x in built['result']['selected']))
        alt=service.alternative(built['result_id'])
        if alt['status']=='candidate':
            self.assertTrue(any(matches_any_keyword(x,['โอโทโร่']) for x in alt['result']['selected']))
        tampered=service.results[built['result_id']]
        tampered['constraints']['required_keywords']=['เมนูไม่มีในร้าน']
        self.assertFalse(service.verify(built['result_id'])['passed'])
        agent.chat('ยกเลิกโอโทโร่')
        self.assertNotIn('โอโทโร่',agent.state.required_keywords)
        mixed=self.agent({'preferred_keywords':['โอโทโร่'],'hard_exclude_keywords':['หมู']})
        mixed.chat('งบ1000บาท 2คน อยากกินโอโทโร่ ขอใส่ในชุดด้วย ไม่กินหมู')
        self.assertIn('โอโทโร่',mixed.state.required_keywords)
        self.assertNotIn('หมู',mixed.state.required_keywords)

    def test_conflict_reports_soft_preference_and_blocks_required(self):
        service=MenuService()
        args=dict(budget=1000,hard_exclude_keywords=['ของดิบ'],preferred_keywords=['ทูน่า'])
        built=service.build(**args)
        self.assertEqual(built['status'],'candidate')
        self.assertIn('ทูน่า',render_menu(built['result']))
        self.assertIn('ขัดกับข้อห้าม',render_menu(built['result']))
        required=service.build(**args,required_keywords=['ทูน่า'])
        self.assertEqual(required['status'],'requires_clarification')
        self.assertIn('ทูน่า',self.agent()._friendly_issues(required['issues']))

    def test_bad_bounds_preserve_valid_intake(self):
        agent=self.agent({'budget':1000,'num_people':2,'min_items':10,'max_items':5,
                          'allergens':['milk'],'preferred_keywords':['แซลมอน']})
        reply=agent.chat('งบ1000บาท 2คน แพ้นม ชอบแซลมอน อย่างน้อย10จาน ไม่เกิน5จาน')
        self.assertIn('เฉพาะจำนวนจาน',reply)
        self.assertEqual((agent.state.budget,agent.state.num_people),(1000,2))
        self.assertEqual(agent.state.allergens,['milk'])
        self.assertEqual(agent.state.preferred_keywords,['แซลมอน'])
        self.assertLessEqual(agent.state.min_items,agent.state.max_items)

    def test_zero_budget_off_menu_and_price_preserve_choices(self):
        agent=self.agent();agent.last_options=[{'total_price':500}]
        agent.pending_allergy_removals=['milk'];agent.state.budget=1000;agent.state.num_people=2
        agent.state.drinks_budget_mode='within'
        self.assertIn('มากกว่า 0',agent.chat('งบ 0 บาท'))
        self.assertIn('ไม่มีเบียร์',agent.chat('เบียร์ 1'))
        self.assertIn('บาท',agent.chat('โอโทโร่ราคาเท่าไหร่'))
        self.assertIn('ยังไม่พบเมนู',agent.chat('เมนูที่ไม่มีในร้านราคาเท่าไหร่'))
        self.assertEqual(agent.last_options,[{'total_price':500}])
        self.assertIn('รวมในงบ\n\nคุณขอแก้',agent.order_summary())

    def test_explicit_cap_prioritizes_variety_and_never_adds_dessert(self):
        built=MenuService().build(budget=1000,max_items=8,max_items_explicit=True,spend_ratio=.8)
        self.assertEqual(built['status'],'candidate')
        rows=built['result']['selected']
        self.assertTrue(all(row['quantity']<=2 for row in rows))
        self.assertGreaterEqual(len(rows),4)
        self.assertFalse(any(row['category']=='ของหวาน' for row in rows))
        favorite={'name_th':'โอโทโร่','price_baht':150,'category':'ปลาดิบ'}
        soup={'name_th':'ซุปไข่','price_baht':40,'category':'ซุป'}
        self.assertGreater(score_item(favorite,['โอโทโร่']),score_item(soup,['โอโทโร่']))

    def test_session_restores_state_and_confirmed_choices_without_credentials(self):
        with tempfile.TemporaryDirectory() as temp:
            store=SessionStore(Path(temp)/'sessions.sqlite3');token='a'*64
            agent=self.agent();agent.state.budget=1000;agent.state.num_people=2
            agent.state.allergens=['milk'];agent.pending_confirmation=True
            agent._api_key='secret-should-never-be-stored'
            history=[{'role':'user','content':'งบ1000บาท'}]
            store.save(token,agent,history)
            restored=self.agent()
            self.assertEqual(store.restore(token,restored),history)
            self.assertEqual(restored.state.allergens,['milk'])
            self.assertTrue(restored.pending_confirmation)
            self.assertNotIn(b'secret-should-never-be-stored',store.path.read_bytes())
            self.assertIsNone(store.restore('b'*64,self.agent()))
            with patch('sushi_budgeteer.persistence.time.time',return_value=10**12):
                self.assertIsNone(store.restore(token,self.agent()))
            store.delete(token);self.assertIsNone(store.restore(token,self.agent()))

    def test_session_rejects_stale_catalogue_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            store=SessionStore(Path(temp)/'s.sqlite3');token='c'*64
            agent=self.agent()
            result=MenuService().build(budget=1000,max_items=8,max_items_explicit=True)['result']
            agent.last_options=[result]
            store.save(token,agent,[])
            self.assertEqual(store.restore(token,self.agent()),[])
            agent.last_options[0]['selected'][0]['price_baht']+=1
            store.save(token,agent,[])
            restored=self.agent()
            self.assertIn('ข้อมูลเมนูเปลี่ยน',store.restore(token,restored)[-1]['content'])
            self.assertFalse(restored.last_options)

    def test_streamlit_refresh_restores_choices_and_price_query_keeps_buttons(self):
        import os
        from streamlit.testing.v1 import AppTest
        from sushi_budgeteer.database import ROOT
        agent=self.agent();agent.state.budget=1000;agent.state.num_people=2
        agent.details_confirmed=True;agent._has_recommended=True
        args=agent.build_arguments()
        result=MenuService().build(**args)['result'];agent.last_options=[result]
        path=Path(self.tmp.name)/'browser.sqlite3'
        token='d'*64;restored=self.agent()
        with patch.dict(os.environ,{'OPENAI_API_KEY':'ui-fixture-only','SUSHI_SESSION_DB':str(path)}):
            page=AppTest.from_file(str(ROOT/'app.py'));page.query_params['session']=token
            page.session_state['agent']=agent
            page.session_state['_agent_key']=('ui-fixture-only','gpt-4o-mini','strict')
            page.session_state['chat_history']=[]
            page.run(timeout=30)
            self.assertFalse(page.exception)
            self.assertTrue(any(b.key=='choose_0' for b in page.button))
            page.chat_input[0].set_value('โอโทโร่ราคาเท่าไหร่').run(timeout=30)
            self.assertFalse(page.exception)
            self.assertTrue(any(b.key=='choose_0' for b in page.button))
            with patch('sushi_budgeteer.agent.BudgeteerAgent',return_value=restored):
                refresh=AppTest.from_file(str(ROOT/'app.py'));refresh.query_params['session']=token
                refresh.run(timeout=30)
            self.assertFalse(refresh.exception)
            self.assertEqual(restored.state.budget,1000)
            self.assertTrue(any(b.key=='choose_0' for b in refresh.button))
            refresh.button(key='choose_0').click().run(timeout=30)
            self.assertFalse(refresh.exception)
            self.assertIsNotNone(restored.food_choice)

    def test_real_mcp_required_dish_build_verify(self):
        import asyncio,os,sys
        from mcp import ClientSession,StdioServerParameters
        from mcp.client.stdio import stdio_client
        from sushi_budgeteer.database import ROOT
        async def run():
            params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')],
                cwd=str(ROOT),env={k:v for k,v in os.environ.items() if k.startswith('SUSHI_')})
            async with stdio_client(params) as (r,w):
                async with ClientSession(r,w) as session:
                    await session.initialize()
                    built=json.loads((await session.call_tool('build_set',dict(budget=1000,
                        required_keywords=['โอโทโร่'],max_items=8,max_items_explicit=True))).content[0].text)
                    self.assertEqual(built['status'],'candidate',built)
                    checked=json.loads((await session.call_tool('verify_set',{'result_id':built['result_id']})).content[0].text)
                    self.assertTrue(checked['passed'])
                    self.assertTrue(any(matches_any_keyword(row,['โอโทโร่']) for row in checked['checked_result']['selected']))
        asyncio.run(run())
