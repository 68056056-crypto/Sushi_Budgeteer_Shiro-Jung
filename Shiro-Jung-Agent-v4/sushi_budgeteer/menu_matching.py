"""Exact catalogue identifiers for orders; fuzzy candidates require user confirmation."""
import difflib
import re
import unicodedata


def normalize(value):
    return re.sub(r'\s+',' ',unicodedata.normalize('NFKC',str(value)).casefold()).strip()


def aliases(row):
    return {normalize(value) for value in [row.get('name_th',''),row.get('name_en',''),
            *str(row.get('keywords','')).split(';')] if normalize(value)}


def exact_match(row,term):
    return bool(normalize(term)) and normalize(term) in aliases(row)


def suggest(term,rows,limit=3):
    """Suggestions are display-only. Never return them as a resolved order."""
    query=normalize(term)
    ranked=[(max((difflib.SequenceMatcher(None,query,name).ratio() for name in aliases(row)),default=0),row)
            for row in rows]
    return [row for score,row in sorted(ranked,key=lambda entry:(-entry[0],entry[1]['item_id']))
            if score>=0.45][:limit]
