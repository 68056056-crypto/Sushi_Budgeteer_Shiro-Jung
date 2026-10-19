"""Capture labelled, offline model-scripted traces through the actual MCP server."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_system import ScriptedModel, READY
from sushi_budgeteer.agent import BudgeteerAgent
from sushi_budgeteer.database import import_csv

scenarios=[
 ('missing_budget',{},[('clarify',{'missing':['budget']}),('final',{})],'ช่วยจัดอาหาร'),
 ('build_verify',READY,[('build_set',{}),('verify_current',{}),('final',{})],'จัดชุดตามข้อมูลที่ระบุ'),
 ('allergen_unknown_blocked',{**READY,'allergens':['crustacean']},[('build_set',{}),('final',{})],'แพ้กุ้ง จัดชุดตามงบ')]
traces=[]
with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ,{'SUSHI_DB_PATH':str(Path(tmp)/'demo.sqlite3'),'SUSHI_DATA_MODE':'strict'}):
    import_csv(ROOT/'sushiro_menu_dataset.csv')
    for name,extraction,steps,message in scenarios:
        agent=BudgeteerAgent(llm=ScriptedModel(steps,extraction))
        answer=agent.chat(message)
        traces.append({'scenario':name,'model':'scripted fake model, not live OpenAI',
                       'tools':'actual MCP stdio + SQLite + OPA','run':agent.run_report(),'answer':answer})
output=ROOT/'artifacts'/'demo-traces.json';output.parent.mkdir(exist_ok=True)
output.write_text(json.dumps(traces,ensure_ascii=False,indent=2))
print('Saved',output)
