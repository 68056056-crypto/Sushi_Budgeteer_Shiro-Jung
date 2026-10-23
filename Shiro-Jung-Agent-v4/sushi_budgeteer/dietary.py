"""Exact, reviewed dietary tags for hard exclusions; never fuzzy-match short words.

These tags describe the educational dataset, not verified restaurant ingredients.
Fuzzy matches are display-only suggestions, never resolved orders or preference identities.
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


# Generic Thai "เนื้อ" is conservatively interpreted as land-animal meat.
# The consumer summary states this scope explicitly before confirmation.
MEAT_TAGS=frozenset({'pork','beef','chicken'})
TAG_GROUPS={word:MEAT_TAGS for word in ('เนื้อ','เนื้อสัตว์บก','meat')}


def exclusion_tags(keyword):
    keyword=str(keyword).strip().lower()
    if keyword in TAG_GROUPS:
        return TAG_GROUPS[keyword]
    tag=TAG_ALIASES.get(keyword)
    return frozenset({tag}) if tag else frozenset()


def requested_tags(keywords):
    return sorted({tag for keyword in keywords or [] for tag in exclusion_tags(keyword)})


def hard_excluded(row, keywords):
    tags=set(str(row.get('dietary_tags','')).split(';')) - {''}
    text=' '.join(str(row.get(key,'')) for key in ('name_th','name_en','keywords')).lower()
    for keyword in keywords or []:
        keyword=str(keyword).strip().lower()
        blocked=exclusion_tags(keyword)
        if blocked:
            if row.get('dietary_status')!='reviewed_dataset' or blocked & tags:
                return True
        elif keyword and keyword in text:
            return True
    return False


def exclusion_label(word):
    return 'เนื้อสัตว์บก (หมู/วัว/ไก่; ไม่รวมปลาและอาหารทะเล)' if word in TAG_GROUPS else word


def expanded_allergens(values):
    tags={str(value).strip().lower() for value in values or []}
    if 'seafood' in tags:
        tags |= {'fish','crustacean','molluscs','echinoderm'}
    return tags


def ingredient_allergens(row):
    """Include explicit land-meat ingredients as additional medical exclusions.

    Reviewed dietary tags are not recipe evidence; unknown status remains unknown.
    """
    reported=set(str(row.get('allergen_tags','')).split(';')) - {''}
    meat=set(str(row.get('dietary_tags','')).split(';')) & MEAT_TAGS
    return reported | meat


def soft_disliked(row, keywords):
    """Land-meat dislikes use tags too, without converting a dislike to exclusion."""
    from .optimizer import matches_any_keyword
    tags=set(str(row.get('dietary_tags','')).split(';'))
    for keyword in keywords or []:
        requested=exclusion_tags(keyword)
        if requested and requested<=MEAT_TAGS:
            if requested & tags:
                return True
        elif matches_any_keyword(row,[keyword]):
            return True
    return False
