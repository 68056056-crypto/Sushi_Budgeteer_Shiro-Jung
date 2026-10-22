"""Normalize harmless clipboard wrappers; reject ambiguous secret contents safely."""
import re


class InvalidAPIKeyFormat(ValueError):
    def __init__(self,message='The API key contains invalid formatting.',issues=()):
        super().__init__(message)
        self.issues=tuple(issues)


def clean_api_key(value):
    if value is None:
        return None
    if not isinstance(value,str):
        raise InvalidAPIKeyFormat(issues=('not_text',))
    key=value.strip()
    # These characters cannot belong to an OpenAI key. Remove clipboard wrappers
    # only at the edges; never join lines or delete characters inside a secret.
    for _ in range(3):
        key=key.strip().strip('\ufeff\u200b\"\'“”‘’').strip()
        key=re.sub(r'^(?:OPENAI_API_KEY|SUSHI_OPENAI_API_KEY)\s*=\s*','',key,count=1)
        if key.startswith('Bearer '):key=key[7:]
    if not key:
        return None
    issues=[]
    if '\n' in key or '\r' in key:issues.append('multiple_lines')
    if any(c.isspace() and c not in '\r\n' for c in key):issues.append('internal_whitespace')
    if any(not 33<=ord(c)<=126 and not c.isspace() for c in key):issues.append('hidden_or_non_ascii')
    if any(c in key for c in ('"',"'",'“','”','‘','’')):issues.append('embedded_quotes')
    if re.search(r'(?:OPENAI_MODEL|OPENAI_API_KEY|SUSHI_OPENAI_API_KEY)\s*=',key):
        issues.append('extra_settings')
    if issues:
        raise InvalidAPIKeyFormat(issues=issues)
    return key
