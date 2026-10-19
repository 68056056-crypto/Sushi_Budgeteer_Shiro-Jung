"""Package explicit public project files only; never collect .env or credentials."""
from pathlib import Path
import argparse
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',default=str(ROOT.parent/'artifacts'/'Shiro-Jung-Agent-v4.zip'))
args=p.parse_args()
root_files=['app.py','mcp_server.py','mcp_client_demo.py','llm_qa.py','test_smoke.py',
            'requirements.txt','requirements.lock','requirements-rag.txt','.env.example',
            '.gitignore','README.md','CODE_REVIEW.md','DATA_DICTIONARY.md','EVALUATION.md','mcp-config.example.json',
            'sushiro_menu_dataset.csv','data/menu.sqlite3','tools/opa/opa','tools/opa/opa.sha256','tools/opa/LICENSE']
paths=[ROOT/x for x in root_files]
for directory,patterns in [('sushi_budgeteer',['*.py']),('tests',['*.py']),('scripts',['*.py','*.sh']),('policies',['*.rego']),('evaluation',['*.json'])]:
    for pattern in patterns: paths.extend((ROOT/directory).glob(pattern))
for name in ['validation-report.json','benchmark.json','demo-traces.json','smoke.log',
             'mcp-demo.log','database-import.json','database-status.json','offline-evaluation.json',
             'live-evaluation.json','live-sessions.json','opa-tests.json','presentation-report.html']:
    path=ROOT/'artifacts'/name
    if path.exists(): paths.append(path)
paths=sorted(set(paths))
for path in paths:
    if not path.is_file(): raise SystemExit(f'Missing required file: {path.name}')
manifest={str(x.relative_to(ROOT)):hashlib.sha256(x.read_bytes()).hexdigest() for x in paths}
output=Path(args.output);output.parent.mkdir(parents=True,exist_ok=True)
with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
    for path in paths: z.write(path,'Shiro-Jung-Agent-v4/'+str(path.relative_to(ROOT)))
    z.writestr('Shiro-Jung-Agent-v4/MANIFEST.sha256.json',json.dumps(manifest,indent=2))
    assert z.testzip() is None
checksum=hashlib.sha256(output.read_bytes()).hexdigest()
output.with_suffix('.zip.sha256').write_text(checksum+'  '+output.name+'\n')
print(json.dumps({'archive':str(output),'files':len(paths)+1,'bytes':output.stat().st_size,'sha256':checksum},indent=2))
