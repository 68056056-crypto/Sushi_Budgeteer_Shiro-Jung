"""Create a standalone presentation report from measured artifacts, with no external assets."""
from pathlib import Path
import sys
import json
import argparse
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sushi_budgeteer import __version__
def read(name):
    p=ROOT/'artifacts'/name
    return json.loads(p.read_text()) if p.exists() else {'status':'not_run'}
data={'validation':read('checks.json').get('validation',{}),'offline':read('offline-evaluation.json'),
      'sessions':read('live-sessions.json'),'benchmark':read('benchmark.json'),
      'latest_live':read('evidence-summary.json').get('latest_live_run',{})}
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live-report',type=Path,help='Override imported verified live report with a newer run')
args=parser.parse_args()
if args.live_report:
    data['sessions']=json.loads(args.live_report.read_text())
encoded=json.dumps(data,ensure_ascii=False).replace('</','<\\/')
html='''<!doctype html><html lang="th"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Shiro-Jung — Evidence Report</title><style>
body{font:16px/1.6 system-ui,sans-serif;max-width:1150px;margin:36px auto;padding:0 20px;background:#fffaf6;color:#25303b}h1,h2{color:#a52e26}.cards{display:flex;flex-wrap:wrap;gap:16px}.card{background:white;padding:18px;border:1px solid #ddd;border-radius:12px;min-width:180px}.value{font-size:30px;font-weight:bold}table{border-collapse:collapse;width:100%;background:white;margin-top:15px}th,td{padding:9px;border-bottom:1px solid #ddd;text-align:left}select,button{font:inherit;padding:6px}.notice{padding:15px;background:#fff0c4;border-radius:8px}.bar{height:13px;margin:3px 0;background:#b5352a}.greedy{background:#4489ab}.random{background:#aaa}small{color:#555}details{margin:12px 0}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style><h1>Shiro-Jung PACKAGE_VERSION — หลักฐานการทำงาน</h1>
<p class="notice">Offline ใช้ MCP + SQLite + OPA จริง ส่วนการตัดสินใจด้วย OpenAI แสดงแยกตามสถานะ live ด้านล่าง ไม่ใช้ผลโมเดลจำลองแทนผลจริง ข้อมูลเมนู/ราคา/allergen ยังไม่ยืนยันกับร้าน</p>
<div id="cards" class="cards"></div><h2>สถานะ LLM จริง</h2><p id="live"></p>
<h2>Evaluation 40 กรณี</h2><label>กรองผล <select id="filter"><option value="all">ทั้งหมด</option><option value="pass">ผ่าน</option><option value="fail">ไม่ผ่าน</option></select></label><div id="evaluation"></div>
<h2>Benchmark ภายใต้ข้อจำกัดเดียวกัน</h2><p>DP, greedy และ random ใช้ objective=budget / diversity=true / spend_ratio=.8 / repeat cap 3 / สูงสุด 60 รายการเหมือนกัน คะแนนเป็น objective ของระบบ ไม่ใช่ความพึงพอใจหรือโภชนาการจริง</p><label>สถานการณ์ <select id="scenario"></select></label><div id="chart"></div>
<h2>ไฟล์หลักฐาน</h2><p>checks.json · offline-evaluation.json · benchmark.json · live-sessions.json · live-trace.md · catalog-audit.json · evidence-summary.json</p><small>รายงานแสดง snapshot ที่อ่านขณะสร้าง; ผล live ต้องตรวจ source_commit และวันที่ของรอบนั้น</small>
<script>const data=DATA;
function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n}
function card(label,value){const c=node('div','');c.className='card';c.append(node('div',label));const v=node('div',value);v.className='value';c.append(v);document.querySelector('#cards').append(c)}
card('Regression tests',data.validation.regression?.run??'ยังไม่รัน');card('Rego tests',data.validation.opa?.rego_tests??'ยังไม่รัน');card('Offline cases',data.offline.executed_cases??0);card('Offline success',data.offline.metrics?((data.offline.metrics.success_rate*100).toFixed(1)+'%'):'ยังไม่รัน');
document.querySelector('#live').textContent='Live consumer sessions: '+data.sessions.status+' ('+(data.sessions.executed_turns??0)+' turns); Live: '+data.sessions.live_llm_tested+'; Gold success: '+data.sessions.success_rate+'; model-selected recommendations: '+data.sessions.model_selected_recommendations+'; Source: '+data.sessions.source_commit;
if(data.latest_live.workflow_status==='success'){document.querySelector('#live').textContent='Current live workflow: SUCCESS; source '+data.latest_live.source_commit+'; corpus '+data.latest_live.sessions_in_corpus+' sessions / '+data.latest_live.gold_turns_in_corpus+' gold. Exit contract confirms live/model-selected >= 1. Raw current artifact not downloaded; bundled per-turn trace is historical source426b48a. See '+data.latest_live.workflow_run_url;}
function evaluations(){const target=document.querySelector('#evaluation');target.replaceChildren();const t=node('table','');const head=node('tr','');for(const label of ['กรณี','คาดหวัง','ผลจริง','ผ่าน','เวลา ms'])head.append(node('th',label));t.append(head);for(const row of data.offline.cases??[]){const f=document.querySelector('#filter').value;if(f==='pass'&&!row.success||f==='fail'&&row.success)continue;const tr=node('tr','');for(const value of [row.id,row.expected,row.actual,row.success?'ผ่าน':'ไม่ผ่าน',row.elapsed_ms])tr.append(node('td',String(value)));t.append(tr)}target.append(t)}
document.querySelector('#filter').onchange=evaluations;evaluations();
const cases=data.benchmark.cases??[];const select=document.querySelector('#scenario');cases.forEach((c,i)=>{const o=node('option',c.full_budget+' บาท / ชอบ '+(c.preferences.join(',')||'ไม่ระบุ')+' / ห้าม '+(c.hard_exclusions.join(',')||'ไม่มี'));o.value=i;select.append(o)});
function chart(){const c=cases[Number(select.value)];if(!c)return;const target=document.querySelector('#chart');target.replaceChildren();const a=c.algorithms;const values=[['DP',a.dp.diminishing_score,'bar'],['Greedy density',a.greedy_density.diminishing_score,'bar greedy'],['Greedy score',a.greedy_score.diminishing_score,'bar greedy'],['Random mean',a.random.means.diminishing_score,'bar random']];const max=Math.max(...values.map(x=>x[1]),1);for(const [label,value,cls]of values){target.append(node('p',label+': '+value.toFixed(3)));const b=node('div','');b.className=cls;b.style.width=(100*value/max)+'%';target.append(b)}target.append(node('small','Random: 100 seeds; DP ใช้งบเต็ม '+(a.dp.share_of_full_budget*100).toFixed(2)+'% / วงเงินอาหาร '+(a.dp.share_of_food_target*100).toFixed(2)+'%, '+a.dp.distinct_dishes+' เมนูไม่ซ้ำ'))}
select.onchange=chart;chart();</script></html>'''.replace('DATA',encoded).replace('PACKAGE_VERSION',__version__)
path=ROOT/'artifacts'/'report.html';path.write_text(html);print(path)
