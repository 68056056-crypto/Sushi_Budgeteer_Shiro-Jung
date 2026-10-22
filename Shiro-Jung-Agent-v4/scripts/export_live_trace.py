"""Export one demonstrable live model-selected recommendation for presentation."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sushi_budgeteer.telemetry import redact


def render_trace(report):
    if report.get('live_llm_tested'):
        for session in report.get('sessions',[]):
            for turn in session.get('turns',[]):
                if not turn.get('success') or not turn.get('model_selected_build_and_verify'):
                    continue
                for run in turn.get('runs',[]):
                    if run.get('model_source')!='live' or not run.get('model_calls',0):
                        continue
                    selected=[event for event in run.get('trace',[]) if event.get('route')=='model_selected']
                    tools={event.get('tool') for event in selected}
                    if not {'build_set','verify_set'}<=tools:
                        continue
                    data=redact({'session':session['id'],'message':turn.get('message'),
                                 'source_commit':report.get('source_commit'),
                                 'model':run.get('model'),'state':turn.get('state'),
                                 'model_selected_events':selected,'usage':run.get('usage')})
                    return '# Live LLM trace for presentation\n\nReal provider run; model selected build_set and verify_set.\n\n```json\n'+json.dumps(data,ensure_ascii=False,indent=2)+'\n```\n'
    return '# Live LLM trace unavailable\n\nNo successful real-provider session with model-selected build_set AND verify_set was recorded. Do not present scripted or fallback traces as live evidence.\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.input.read_text()) if args.input.exists() else {}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(render_trace(report),encoding='utf-8')

if __name__=='__main__':main()
