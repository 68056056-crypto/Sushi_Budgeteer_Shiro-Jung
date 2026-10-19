"""Invoke pinned OPA locally. Missing executable, timeout, or undefined output denies."""
from __future__ import annotations
import json
import os
from pathlib import Path
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]

def binary_path():
    return Path(os.getenv('SUSHI_OPA_BINARY',str(ROOT/'tools'/'opa'/('opa.exe' if os.name=='nt' else 'opa'))))

def evaluate(facts):
    start=time.perf_counter()
    try:
        result=subprocess.run([str(binary_path()),'eval','--format=json','--data',
            str(ROOT/'policies'/'recommendation.rego'),'--stdin-input','data.shiro.decision'],
            input=json.dumps(facts),text=True,capture_output=True,timeout=5,check=True)
        value=json.loads(result.stdout)['result'][0]['expressions'][0]['value']
        if type(value.get('allow')) is not bool or not isinstance(value.get('deny_reasons'),list):
            raise ValueError('invalid OPA decision')
        return {**value,'engine':'OPA','elapsed_ms':round((time.perf_counter()-start)*1000,3)}
    except (OSError,subprocess.SubprocessError,ValueError,KeyError,IndexError,TypeError):
        return {'allow':False,'deny_reasons':['opa_unavailable_or_invalid'],
                'policy_version':'unknown','engine':'OPA',
                'elapsed_ms':round((time.perf_counter()-start)*1000,3)}
