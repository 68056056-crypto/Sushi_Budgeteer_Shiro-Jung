"""Exact, reviewed dietary tags for hard exclusions; never fuzzy-match short words.

These tags describe the educational dataset, not verified restaurant ingredients.
Fuzzy matching remains available only for search and soft preferences.
"""
from __future__ import annotations

TAG_ALIASES = {
    'ดิบ': 'raw', 'ของดิบ': 'raw', 'อาหารดิบ': 'raw', 'ปลาดิบ': 'raw', 'raw': 'raw',
    'หมู': 'pork', 'เนื้อหมู': 'pork', 'pork': 'pork',
    'วัว': 'beef', 'เนื้อวัว': 'beef', 'beef': 'beef',
    'ไก่': 'chicken', 'chicken': 'chicken',
    'ปลา': 'fish', 'fish': 'fish', 'กุ้ง': 'crustacean', 'crustacean': 'crustacean',
    'หอย': 'molluscs', 'molluscs': 'molluscs',
    'ไข่': 'egg', 'egg': 'egg', 'นม': 'milk', 'milk': 'milk',
    'ถั่วเหลือง': 'soy', 'soy': 'soy', 'แป้งสาลี': 'gluten', 'gluten': 'gluten',
    'งา': 'sesame', 'sesame': 'sesame',
}


def requested_tags(keywords):
    return sorted({TAG_ALIASES[str(word).strip().lower()] for word in keywords or []
                   if str(word).strip().lower() in TAG_ALIASES})


def hard_excluded(row, keywords):
    tags=set(str(row.get('dietary_tags','')).split(';')) - {''}
    text=' '.join(str(row.get(key,'')) for key in ('name_th','name_en','keywords')).lower()
    for keyword in keywords or []:
        keyword=str(keyword).strip().lower()
        tag=TAG_ALIASES.get(keyword)
        if tag:
            # An unreviewed row cannot demonstrate compliance with a tagged exclusion.
            if row.get('dietary_status')!='reviewed_dataset' or tag in tags:
                return True
        elif keyword and keyword in text:
            return True
    return False


def expanded_allergens(values):
    tags={str(value).strip().lower() for value in values or []}
    if 'seafood' in tags:
        tags |= {'fish','crustacean','molluscs','echinoderm'}
    return tags
