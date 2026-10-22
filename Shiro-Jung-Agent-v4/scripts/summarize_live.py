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
    keys=('status','live_llm_tested','success_rate','model_selected_recommendations','executed_turns','successful_model_responses','model_error_count')
    lines=['## Live LLM evidence','']+[f'- {key}: `{report.get(key,"not recorded")}`' for key in keys]
    hints={'credential_format':'Edit the repository secret: paste only the API key on one line, without quotes, assignment or hidden characters.',
           'authentication':'Check repository secret OPENAI_API_KEY; verify the key is valid and belongs to the intended API project.',
           'quota_or_billing':'Check API project credits, billing and spending limits; ChatGPT subscriptions do not fund API usage.',
           'rate_limit':'Check API rate limits and retry after the provider wait period.',
           'model_access':'Check that the API project can access the configured model.',
           'permission_denied':'Check API project permissions and provider access restrictions.',
           'connection':'Check runner access to the API endpoint.',
           'timeout':'Check provider availability and request timeout.',
           'invalid_model_response':'A response was received but extraction validation failed; inspect the turn trace.'}
    for category,count in report.get('error_categories',{}).items():
        lines+=['',f'- Error category: `{category}` ({count})',hints.get(category,'Inspect the safe error fields in the JSON artifact and job log.')]
    lines+=['','executed_turns counts conversation attempts, not successful API responses.',
            'A scripted run is not live evidence. Review the JSON trace before presenting.','']
    summary='\n'.join(lines)
    if os.getenv('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'],'a',encoding='utf-8') as stream:
            stream.write(summary)
    print(summary)

if __name__=='__main__':main()
