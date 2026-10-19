"""Run offline regression + legacy smoke; write a reproducible JSON summary."""
from pathlib import Path
import datetime
import json
import os
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.chdir(ROOT)
report_dir=ROOT/'artifacts'
report_dir.mkdir(exist_ok=True)
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(verbosity=2).run(suite)
env={**os.environ,'SUSHI_DATA_MODE':'simulation'}
smoke=subprocess.run([sys.executable,'test_smoke.py'],cwd=ROOT,env=env,capture_output=True,text=True)
(report_dir/'smoke.log').write_text(smoke.stdout+smoke.stderr)
from sushi_budgeteer.opa import binary_path
opa=subprocess.run([str(binary_path()),'test',str(ROOT/'policies'),'--format=json'],capture_output=True,text=True)
opa_stdout=(opa.stdout or json.dumps({'error':'OPA test runner failed'}))
opa_stdout=opa_stdout.replace(json.dumps(str(ROOT))[1:-1]+json.dumps(os.sep)[1:-1],'').replace(ROOT.as_posix()+'/','')
(report_dir/'opa-tests.json').write_text(opa_stdout)
opa_results=json.loads(opa.stdout) if opa.returncode==0 else []
report={'checked_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'python':sys.version.split()[0],'platform':sys.platform,'release':'4.0.0', 'regression':{'run':result.testsRun,'failures':len(result.failures),
        'errors':len(result.errors),'skipped':len(result.skipped)},
        'legacy_smoke':{'exit_code':smoke.returncode,'passed_checks':smoke.stdout.count('[PASS]'),
        'mode':'simulation'},'real_mcp_subprocess_tested':True,
        'agent_model':'scripted fake model in tests; real MCP tools',
        'opa':{'exit_code':opa.returncode,'rego_tests':len(opa_results)},'live_llm_api_tested':False,'official_sources_verified':False}
(report_dir/'validation-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
sys.exit(0 if result.wasSuccessful() and smoke.returncode==0 and opa.returncode==0 else 1)
