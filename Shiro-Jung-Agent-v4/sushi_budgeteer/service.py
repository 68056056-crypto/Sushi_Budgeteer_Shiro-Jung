"""Per-process MCP service. Result IDs refer to server-held trusted snapshots."""
from __future__ import annotations
import copy
import json
from .database import records
from .policy import validate_result, DISCLAIMER
from .tools import build_optimal_set
from .explain import explain

class MenuService:
    def __init__(self):
        self.results = {}

    def build(self, **kwargs):
        result=json.loads(build_optimal_set.invoke(kwargs))
        # The caller never supplies the result to be verified or its trusted constraints.
        self.results[result['result_id']]=copy.deepcopy(result)
        if len(self.results)>20: self.results.pop(next(iter(self.results)))
        menu=records()
        check=validate_result(result, menu)
        if not check['passed']:
            return {'status':'requires_clarification','issues':check['issues'],
                    'disclaimer':DISCLAIMER,'data_mode':result['data_mode'],
                    'policy_decision':check.get('policy_decision')}
        result['explanation']=explain(result,menu)
        result['policy_decision']=check['policy_decision']
        self.results[result['result_id']]=copy.deepcopy(result)
        return {'status':'candidate','result_id':result['result_id'],'result':result,
                'instruction':'Call verify_set with this result_id before recommending.'}

    def alternative(self, result_id):
        """Diversify food only; never relax the original dietary constraints."""
        original=self.results.get(result_id)
        if original is None or not self.verify(result_id)['passed']:
            return {'status':'unavailable'}
        food=[x for x in original['selected'] if x['category'] not in {'เครื่องดื่ม','ของหวาน'}]
        # A bounded search; fixed drinks/desserts and all preferences stay unchanged.
        for item in food[:3]:
            args=copy.deepcopy(original['constraints'])
            args['excluded_item_ids']=list(dict.fromkeys([*args.get('excluded_item_ids',[]),item['item_id']]))
            built=self.build(**args)
            if built['status']=='candidate':
                return built
        return {'status':'unavailable'}

    def verify(self, result_id):
        result=self.results.get(result_id)
        if result is None:
            return {'passed':False,'issues':['result_id ไม่มีใน MCP process/session นี้']}
        try:
            payload=validate_result(result, records())
        except (ValueError, TypeError, KeyError) as exc:
            payload={'passed':False,'issues':[str(exc)]}
        payload['result_id']=result_id
        if payload['passed']:
            payload['checked_result']=copy.deepcopy(result)
            payload['checked_result']['policy_decision']=payload['policy_decision']
        if not payload['passed']: payload.pop('checked_result',None)
        return payload
