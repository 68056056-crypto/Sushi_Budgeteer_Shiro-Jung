"""Write only non-secret evaluation aggregates to the Actions job summary."""
import argparse
import json
import os
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input',type=Path,required=True)
    args=parser.parse_args()
    report=json.loads(args.input.read_text()) if args.input.exists() else {'status':'report_missing'}
    keys=('status','live_llm_tested','success_rate','model_selected_recommendations','executed_turns')
    lines=['## Live LLM evidence','']+[f'- {key}: `{report.get(key,"not recorded")}`' for key in keys]
    lines+=['','A scripted run is not live evidence. Review the JSON trace before presenting.','']
    summary='\n'.join(lines)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as stream:
            stream.write(summary)
    print(summary)

if __name__=='__main__':main()
