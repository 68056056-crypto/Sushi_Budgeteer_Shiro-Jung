"""Offline regression and real stdio MCP integration; no paid API calls."""
import asyncio
import csv
import itertools
import json
import os
from pathlib import Path
import random
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from langchain_core.messages import AIMessage
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from sushi_budgeteer.database import ROOT, import_csv, records, cents, catalog_revision
from sushi_budgeteer.optimizer import _dp_knapsack_01
from sushi_budgeteer.policy import validate_result
from sushi_budgeteer.service import MenuService
from sushi_budgeteer.agent import BudgeteerAgent

class CatalogTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'menu.sqlite3'
        self.env=patch.dict(os.environ,{'SUSHI_DB_PATH':str(self.db),'SUSHI_DATA_MODE':'strict'})
        self.env.start()
        import_csv(ROOT/'sushiro_menu_dataset.csv')
    def tearDown(self):
        self.env.stop();self.tmp.cleanup()

    def test_sqlite_is_live_source(self):
        with sqlite3.connect(self.db) as c: c.execute("UPDATE menu SET price_baht=77.25 WHERE item_id='S001'")
        self.assertEqual(next(x for x in records() if x['item_id']=='S001')['price_baht'],77.25)

    def test_import_rejects_duplicate_without_losing_database(self):
        source=Path(self.tmp.name)/'bad.csv'
        source.write_text('item_id,name_th,category,price_baht,allergens_verified\nx,a,c,1,\nx,b,c,2,\n')
        with self.assertRaises(ValueError): import_csv(source)
        self.assertEqual(len(records()),41)

    def test_unknown_allergen_fails_closed(self):
        result=MenuService().build(budget=300,allergens=['crustacean'])
        self.assertEqual(result['status'],'requires_clarification')
        self.assertNotIn('result',result)

    def test_simulation_explicitly_labelled(self):
        with patch.dict(os.environ,{'SUSHI_DATA_MODE':'simulation'}):
            s=MenuService();r=s.build(budget=300,allergens=['crustacean'])
            self.assertEqual(r['result']['data_mode'],'simulation')
            self.assertTrue(s.verify(r['result_id'])['passed'])

    def test_confirmed_menu_allergy_filter(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE menu SET allergen_status='confirmed', allergen_source_url='https://example.org/test-fixture', checked_at='2026-01-01'")
        s=MenuService();r=s.build(budget=300,allergens=['egg'])
        self.assertEqual(r['status'],'candidate')
        self.assertFalse(any('egg' in x['allergens_verified'].split(';') for x in r['result']['selected']))
        self.assertTrue(s.verify(r['result_id'])['passed'])

    def test_unknown_allergen_blocks_even_confirmed_catalog(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE menu SET allergen_status='confirmed'")
        self.assertEqual(MenuService().build(budget=300,allergens=['unknown spice'])['status'],'requires_clarification')

    def test_seafood_alias_blocks_fish(self):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE menu SET allergen_status='confirmed'")
        s=MenuService();r=s.build(budget=300,allergens=['seafood'])
        self.assertEqual(r['status'],'candidate')
        self.assertFalse(any(set(x['allergens_verified'].split(';')) & {'fish','crustacean','molluscs','seafood'} for x in r['result']['selected']))

    def test_fixed_selection_tampering_rejected(self):
        s=MenuService();r=s.build(budget=300,drink_selection=['ชาเขียวร้อน'],drink_quantity=1)
        rid=r['result_id']
        s.results[rid]['constraints']['drink_selection']=['โค้ก']
        self.assertFalse(s.verify(rid)['passed'])

    def test_result_cannot_cross_service_sessions(self):
        a,b=MenuService(),MenuService()
        r=a.build(budget=300)
        self.assertTrue(a.verify(r['result_id'])['passed'])
        self.assertFalse(b.verify(r['result_id'])['passed'])

    def test_catalog_change_invalidates_candidate(self):
        s=MenuService();r=s.build(budget=300)
        with sqlite3.connect(self.db) as c: c.execute("UPDATE menu SET price_baht=price_baht+1")
        self.assertFalse(s.verify(r['result_id'])['passed'])

    def test_amount_tampering_rejected(self):
        s=MenuService();r=s.build(budget=300);rid=r['result_id']
        s.results[rid]['total_price']=0
        self.assertFalse(s.verify(rid)['passed'])

    def test_quantity_tampering_rejected(self):
        s=MenuService();r=s.build(budget=300);rid=r['result_id']
        s.results[rid]['selected'][0]['quantity']=999
        self.assertFalse(s.verify(rid)['passed'])

    def test_fixed_allergen_blocked(self):
        with patch.dict(os.environ,{'SUSHI_DATA_MODE':'simulation'}):
            s=MenuService();r=s.build(budget=500,allergens=['milk'],
                drink_selection=['มัทฉะลาเต้เย็น'],drink_quantity=1)
            self.assertEqual(r['status'],'requires_clarification')

    def test_minimum_is_enforced(self):
        self.assertEqual(MenuService().build(budget=40,min_items=3)['status'],'requires_clarification')

    def test_fixed_count_limit_is_enforced(self):
        r=MenuService().build(budget=300,max_items=1,drink_selection=['โค้ก'],drink_quantity=3)
        self.assertEqual(r['status'],'requires_clarification')

    def test_free_drink_is_not_a_food_set(self):
        r=MenuService().build(budget=1,drink_selection=['ชาเขียวร้อน'],drink_quantity=1)
        self.assertEqual(r['status'],'requires_clarification')

    def test_separate_budget_mode(self):
        s=MenuService();r=s.build(budget=300,drink_selection=['โค้ก'],drink_quantity=2,drinks_separate_from_budget=True)
        self.assertEqual(r['status'],'candidate')
        self.assertGreater(r['result']['total_price'],r['result']['food_total_price'])
        self.assertTrue(s.verify(r['result_id'])['passed'])

    def test_missing_fixed_choice_rejected(self):
        with self.assertRaises(ValueError):
            MenuService().build(budget=300,drink_selection=['nonexistent drink xyz'],drink_quantity=1)

    def test_real_mcp_database_and_session(self):
        async def run():
            params=StdioServerParameters(command=sys.executable,args=[str(ROOT/'mcp_server.py')],cwd=str(ROOT),
                env={'SUSHI_DB_PATH':str(self.db),'SUSHI_DATA_MODE':'strict'})
            async with stdio_client(params) as (r,w):
                async with ClientSession(r,w) as s:
                    await s.initialize()
                    names={t.name for t in (await s.list_tools()).tools}
                    self.assertTrue({'search_menu','get_menu_item','build_set','verify_set'}<=names)
                    async def call(name,args):
                        result=await s.call_tool(name,args)
                        self.assertFalse(result.isError,result)
                        return json.loads(result.content[0].text)
                    self.assertEqual((await call('database_status',{}))['row_count'],41)
                    item=(await call('get_menu_item',{'item_id':'S001'}))['item']
                    self.assertEqual(item['price_baht'],40)
                    with sqlite3.connect(self.db) as c: c.execute("UPDATE menu SET price_baht=42.25 WHERE item_id='S001'")
                    self.assertEqual((await call('get_menu_item',{'item_id':'S001'}))['item']['price_baht'],42.25)
                    self.assertGreater((await call('search_menu',{'keyword':'แซลมอน'}))['count'],0)
                    candidate=await call('build_set',{'budget':300})
                    verified=await call('verify_set',{'result_id':candidate['result_id']})
                    self.assertTrue(verified['passed'])
                    self.assertFalse((await call('verify_set',{'result_id':'fake'}))['passed'])
                    self.assertGreater(len(json.loads((await s.read_resource('sushiro://menu/catalog')).contents[0].text)),0)
                    self.assertTrue((await s.get_prompt('budget_optimizer',{'budget':'300'})).messages)
        asyncio.run(run())

class UITest(unittest.TestCase):
    def test_page_without_api_key(self):
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ,{'OPENAI_API_KEY':'','SUSHI_OPENAI_API_KEY':''}):
            app=AppTest.from_file(str(ROOT/'app.py')).run(timeout=30)
            self.assertFalse(app.exception)
            self.assertTrue(app.warning)
            self.assertEqual(len(app.error),1)
            self.assertIn('OPENAI_API_KEY',app.error[0].value)
            app.selectbox[0].set_value('simulation').run()
            self.assertFalse(app.exception)

class OptimizerTest(unittest.TestCase):
    def test_count_counterexample_fixed(self):
        items=[{'item_id':str(i),'price_baht':p,'score':s} for i,(p,s) in enumerate([(1,2),(1,2),(2,3),(2,3)])]
        self.assertEqual(sum(x['score'] for x in _dp_knapsack_01(items,4,max_items=2)),6)
    def test_decimal_budget(self):
        items=[{'item_id':str(i),'price_baht':1.4,'score':1} for i in range(2)]
        self.assertEqual(len(_dp_knapsack_01(items,2.4)),1)
    def test_matches_exhaustive_optimum(self):
        rng=random.Random(46)
        for _ in range(35):
            items=[{'item_id':str(i),'price_baht':rng.randint(1,20)/10,'score':rng.randint(0,10)} for i in range(7)]
            budget=rng.randint(10,60)/10;limit=rng.randint(1,4);minimum=rng.randint(0,limit)
            feasible=[sub for n in range(minimum,limit+1) for sub in itertools.combinations(items,n)
                      if sum(cents(x['price_baht']) for x in sub)<=cents(budget)]
            actual=_dp_knapsack_01(items,budget,max_items=limit,min_items=minimum)
            if not feasible: self.assertEqual(actual,[]); continue
            metric=lambda sub:(sum(x['score'] for x in sub),sum(cents(x['price_baht']) for x in sub))
            self.assertEqual(metric(actual),max(map(metric,feasible)))
    def test_invalid_money(self):
        for x in ['nan','inf',-1,'0.001']:
            with self.assertRaises(ValueError): cents(x)

READY={'budget':300,'num_people':2,'allergy_check_answered':True,
       'drink_selection':['ชาเขียวร้อน'],'drink_quantity':2,
       'drinks_budget_mode':'within','wants_dessert':False}

class ScriptedModel:
    """Deterministic fake model only; MCP is a real subprocess in these tests."""
    def __init__(self,steps,extraction=None):
        self.steps=list(steps);self.extraction=extraction if extraction is not None else READY
    def invoke(self,messages): return AIMessage(content=json.dumps(self.extraction))
    def bind_tools(self,schemas): return self
    async def ainvoke(self,messages):
        step=self.steps.pop(0) if self.steps else ('final',{})
        if step[0]=='final': return AIMessage(content='untrusted LLM recommendation')
        name,args=step
        if name=='verify_current':
            previous=json.loads(next(m.content for m in reversed(messages) if m.type=='tool' and 'result_id' in m.content))
            name='verify_set';args={'result_id':previous['result_id']}
        return AIMessage(content='',tool_calls=[{'id':f'call-{len(messages)}','name':name,'args':args}])

# Define independent Agent tests using the same fixture setup/teardown.
class AgentFlowTest(unittest.TestCase):
    setUp=CatalogTest.setUp
    tearDown=CatalogTest.tearDown
    def test_model_mcp_loop_and_constraint_binding(self):
        a=BudgeteerAgent(llm=ScriptedModel([('build_set',{'budget':99999,'allergens':[]}),('verify_current',{}),('final',{})]))
        answer=a.chat('งบ300 2คน ชาเขียวร้อน2แก้ว รวมในงบ ไม่รับของหวาน ไม่มีแพ้')
        self.assertIn('ผ่านการตรวจ',answer)
        self.assertLessEqual(a.state.last_result['total_price'],300)
        self.assertEqual(a.last_trace[0]['arguments']['budget'],300)
        self.assertEqual([x['tool'] for x in a.last_trace],['build_set','verify_set'])
    def test_no_verify_means_no_recommendation(self):
        a=BudgeteerAgent(llm=ScriptedModel([('build_set',{}),('final',{})]))
        answer=a.chat('จัดชุด')
        self.assertNotIn('ผ่านการตรวจ',answer)
        self.assertNotIn('untrusted',answer)
        self.assertIsNone(a.state.last_result)
    def test_missing_data_gates_build(self):
        a=BudgeteerAgent(llm=ScriptedModel([('build_set',{}),('clarify',{'missing':['budget']}),('final',{})],{}))
        answer=a.chat('ช่วยจัดอาหาร')
        self.assertIn('งบประมาณ',answer)
        self.assertTrue(any('error' in x for x in a.last_trace))
    def test_failed_allergen_plan_not_released(self):
        extraction={**READY,'allergens':['crustacean']}
        a=BudgeteerAgent(llm=ScriptedModel([('build_set',{}),('final',{})],extraction))
        answer=a.chat('แพ้กุ้ง')
        self.assertNotIn('ผ่านการตรวจ',answer)
        self.assertIn('ยังจัดชุด',answer)
    def test_state_is_not_shared(self):
        a=BudgeteerAgent(llm=ScriptedModel([('clarify',{'missing':['num_people']}),('final',{})],{'budget':300}))
        b=BudgeteerAgent(llm=ScriptedModel([],{}))
        a.chat('งบ300')
        self.assertEqual(a.state.budget,300)
        self.assertIsNone(b.state.budget)
    def test_database_search_output(self):
        a=BudgeteerAgent(llm=ScriptedModel([('get_menu_item',{'item_id':'S001'}),('final',{})],{}))
        self.assertIn('40.00',a.chat('ราคาแซลมอน'))
    def test_invalid_extraction_fails_closed(self):
        a=BudgeteerAgent(llm=ScriptedModel([],{'budget':float('nan')}))
        self.assertIn('อ่านข้อมูล',a.chat('จัดชุด'))
    def test_unknown_allergy_is_preserved(self):
        a=BudgeteerAgent(llm=ScriptedModel([('clarify',{'missing':['budget']}),('final',{})],{'allergens':['unknown spice']}))
        a.chat('แพ้เครื่องเทศ')
        self.assertIn('unknown spice',a.state.allergens)


if __name__=='__main__': unittest.main()
