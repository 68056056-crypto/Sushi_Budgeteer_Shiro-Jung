"""Run every evidence step in order and rebuild the HTML report (Windows/macOS/Linux).

Offline steps always run. Live LLM steps run only when SUSHI_OPENAI_API_KEY or
OPENAI_API_KEY is set (e.g. in .env); otherwise they are reported as skipped and
no simulated result is written in their place.

    python scripts/collect_evidence.py            # offline + live smoke (3 cases)
    python scripts/collect_evidence.py --full     # offline + all live cases + sessions
    python scripts/collect_evidence.py --offline  # never call the LLM
"""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def load_dotenv() -> None:
    env = ROOT / '.env'
    if not env.exists():
        return
    for line in env.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, value = line.split('=', 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def run(label: str, *args: str, log: str | None = None) -> int:
    print(f'\n=== {label} ===', flush=True)
    if log is None:
        code = subprocess.run([sys.executable, *args], cwd=ROOT, env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'}).returncode
    else:
        proc = subprocess.run([sys.executable, *args], cwd=ROOT, capture_output=True, text=True, encoding='utf-8',
                              env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONIOENCODING': 'utf-8'})
        print(proc.stdout + proc.stderr, end='')
        (ROOT / 'artifacts' / log).write_text(proc.stdout + proc.stderr, encoding='utf-8')
        code = proc.returncode
    print(f'--- {label}: exit {code}', flush=True)
    return code


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--full', action='store_true', help='run all live cases and multi-turn sessions')
    p.add_argument('--offline', action='store_true', help='skip live LLM steps')
    args = p.parse_args()
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except (AttributeError, ValueError):
        pass
    load_dotenv()
    results = {}
    results['install_opa'] = run('OPA binary check', 'scripts/install_opa.py')
    (ROOT / 'artifacts').mkdir(exist_ok=True)
    results['database_import'] = run('Import CSV -> SQLite', '-m', 'sushi_budgeteer.database', 'import', log='database-import.json')
    results['database_status'] = run('Database status', '-m', 'sushi_budgeteer.database', 'status', log='database-status.json')
    results['checks'] = run('Regression + smoke + OPA tests', 'scripts/run_checks.py', '--output-dir', 'artifacts/review-round2')
    results['mcp_demo'] = run('MCP client demo', 'mcp_client_demo.py', log='mcp-demo.log')
    results['offline_eval'] = run('Offline evaluation (40 cases)', 'scripts/evaluate.py', '--mode', 'offline', '--output', 'artifacts/review-round2-followup/offline-evaluation.json')
    results['benchmark'] = run('Benchmark DP vs greedy vs random', 'scripts/benchmark.py', '--output', 'artifacts/review-round2-followup/benchmark-production.json')
    results['catalog_audit'] = run('Menu evidence audit', 'scripts/catalog_audit.py')
    results['demo_traces'] = run('Demo traces', 'scripts/capture_demo.py')
    has_key = bool(os.getenv('SUSHI_OPENAI_API_KEY') or os.getenv('OPENAI_API_KEY'))
    if args.offline or not has_key:
        reason = 'offline flag' if args.offline else 'no API key in environment or .env'
        print(f'\n=== Live LLM steps skipped ({reason}) ===')
        results['live'] = 'skipped: ' + reason
    else:
        limit = '40' if args.full else '3'
        results['live_eval'] = run(f'Live evaluation (limit {limit})', 'scripts/evaluate.py', '--mode', 'live', '--limit', limit)
        if args.full:
            results['live_sessions'] = run('Live multi-turn sessions', 'scripts/live_sessions.py', '--scenarios', 'evaluation/round2_sessions.json', '--output', 'artifacts/review-round2-followup/live-status.json')
    results['report'] = run('Build review-round2-followup-report.html', 'scripts/build_report.py')
    print('\n' + json.dumps(results, indent=2))
    print('\nOpen artifacts/review-round2-followup-report.html in a browser to review the evidence.')
    hard_fail = any(isinstance(v, int) and v not in (0,) for k, v in results.items() if not k.startswith('live'))
    return 1 if hard_fail else 0


if __name__ == '__main__':
    sys.exit(main())
