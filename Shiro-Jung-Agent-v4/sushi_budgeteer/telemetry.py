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
