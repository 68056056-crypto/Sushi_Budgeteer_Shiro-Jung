"""Export observable events and token counts; no prompts or hidden reasoning."""
from __future__ import annotations
import os
import re

SECRET_FIELDS={'api_key','openai_api_key','sushi_openai_api_key','authorization','password','secret'}

def redact(value):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if k.lower() in SECRET_FIELDS else redact(v)) for k,v in value.items()}
    if isinstance(value,list): return [redact(x) for x in value]
    if isinstance(value,str):
        for name in ('OPENAI_API_KEY','SUSHI_OPENAI_API_KEY'):
            secret=os.getenv(name)
            if secret: value=value.replace(secret,'[REDACTED]')
        value=re.sub(r'\bsk-[A-Za-z0-9_-]{12,}','[REDACTED]',value)
        value=re.sub(r'(?i)Bearer\s+[^\s"\']+','Bearer [REDACTED]',value)
    return value


def model_error(error, phase):
    """Safe diagnostic fields only: never export raw exception/body/header content."""
    while getattr(error,'exceptions',None):
        error=error.exceptions[0]
    name=type(error).__name__
    status=getattr(error,'status_code',None)
    status=status if isinstance(status,int) else None
    body=getattr(error,'body',None)
    code=getattr(error,'code',None)
    if isinstance(body,dict):
        details=body.get('error',body)
        if isinstance(details,dict):code=details.get('code') or code
    known={'invalid_api_key','insufficient_quota','rate_limit_exceeded','model_not_found',
           'billing_hard_limit_reached','unsupported_country_region_territory'}
    code=code if isinstance(code,str) and code in known else None
    if code in {'insufficient_quota','billing_hard_limit_reached'}:
        category='quota_or_billing'
    elif status==401 or name=='AuthenticationError':category='authentication'
    elif status==429:category='rate_limit'
    elif code=='model_not_found' or status==404:category='model_access'
    elif status==403:category='permission_denied'
    elif 'Timeout' in name:category='timeout'
    elif name=='APIConnectionError':category='connection'
    elif name in {'JSONDecodeError','ValidationError','ValueError'}:category='invalid_model_response'
    else:category='provider_or_runtime_error'
    return {'phase':phase,'type':name,'category':category,'status_code':status,'code':code}
