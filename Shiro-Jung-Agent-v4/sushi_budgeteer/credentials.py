"""Validate the shape of a secret without exposing its value or testing its validity."""


class InvalidAPIKeyFormat(ValueError):
    pass


def clean_api_key(value):
    if value is None:
        return None
    if not isinstance(value,str):
        raise InvalidAPIKeyFormat('API key must be a single-line secret value.')
    key=value.strip()
    if not key:
        return None
    if (key.startswith(('OPENAI_API_KEY=','SUSHI_OPENAI_API_KEY=','Bearer '))
            or key.startswith(('"',"'")) or key.endswith(('"',"'"))
            or any(not 33<=ord(char)<=126 for char in key)):
        raise InvalidAPIKeyFormat('Paste only the API key in one line, without quotes, assignment, spaces or hidden characters.')
    return key
