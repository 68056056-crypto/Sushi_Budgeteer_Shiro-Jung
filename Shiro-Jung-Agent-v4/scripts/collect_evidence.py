"""Reproduce offline evidence without paid API calls or replacing an existing catalog."""
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
STEPS=[
    ('OPA verification',['scripts/install_opa.py']),
    ('Regression, smoke and Rego',['scripts/run_checks.py']),
    ('40 offline gold cases',['scripts/evaluate.py']),
    ('Production benchmark',['scripts/benchmark.py']),
    ('Menu evidence audit',['scripts/catalog_audit.py']),
    ('Local evidence dashboard',['scripts/build_report.py']),
]


def main():
    for label,command in STEPS:
        print(label,flush=True)
        result=subprocess.run([sys.executable,*command],cwd=ROOT)
        if result.returncode:
            return result.returncode
    print('Evidence: artifacts/; dashboard: artifacts/report.html. No live API calls were made.')
    return 0

if __name__=='__main__':sys.exit(main())
