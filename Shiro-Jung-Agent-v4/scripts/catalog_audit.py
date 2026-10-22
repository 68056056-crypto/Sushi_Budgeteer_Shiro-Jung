"""Export a menu-evidence checklist without changing catalog status or inventing sources."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from sushi_budgeteer.database import records, catalog_revision


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'artifacts'/'review-round2-followup'/'catalog-audit.json')
    parser.add_argument('--checklist',type=Path)
    args=parser.parse_args()
    rows=records()
    checklist=[]
    for row in rows:
        missing=[name for name in ('source_url','allergen_source_url','checked_at') if not row.get(name)]
        checklist.append({'item_id':row['item_id'],'name_th':row['name_th'],
                          'price_baht':row['price_baht'],'price_status':row['price_status'],
                          'allergen_tags':row['allergen_tags'],'allergen_status':row['allergen_status'],
                          'source_url':row.get('source_url',''),'allergen_source_url':row.get('allergen_source_url',''),
                          'checked_at':row.get('checked_at',''),'missing_evidence':';'.join(missing),
                          'allergen_review_reason':row.get('allergen_review_reason',''),
                          'allergen_reviewed_by':row.get('allergen_reviewed_by',''),
                          'branch':'','evidence_file':'','contact_date':'','response_status':'not_contacted',
                          'reviewer_notes':''})
    report={'created_at':datetime.now(timezone.utc).isoformat(),'catalog_revision':catalog_revision(rows),
            'row_count':len(rows),'unknown_allergens':sum(row['allergen_status']!='confirmed' for row in rows),
            'unverified_prices':sum(row['price_status']!='confirmed' for row in rows),
            'rows_missing_evidence':sum(bool(row['missing_evidence']) for row in checklist),
            'catalog_modified':False,'note':'A reviewer must inspect real menu-specific ingredient/price evidence; this audit never confirms recipes.',
            'items':checklist}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    if args.checklist:
        args.checklist.parent.mkdir(parents=True,exist_ok=True)
        with args.checklist.open('w',encoding='utf-8-sig',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(checklist[0]))
            writer.writeheader();writer.writerows(checklist)
    print(json.dumps({key:value for key,value in report.items() if key!='items'},ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':
    sys.exit(main())
