"""Thai packaged-food allergen group registry, separate from recipe verification.

Reference supplied with the user's audit CSV: MOPH Notification 450 (2567), 5(6).
This registry is not a legal certification, and category mapping cannot establish
absence, concentration of sulphites, or cross-contact in a restaurant recipe.
"""
THAI_LAW_REFERENCE = 'ประกาศกระทรวงสาธารณสุข (ฉบับที่ 450) พ.ศ. 2567 ข้อ 5(6)'
THAI_LAW_URL = 'https://food.fda.moph.go.th/media.php?id=654869394207416320&name=P450.pdf'
THAI_ALLERGEN_GROUPS = {
    'gluten': 'ธัญพืชที่มีกลูเตนและผลิตภัณฑ์',
    'crustacean': 'สัตว์น้ำที่มีเปลือกแข็งและผลิตภัณฑ์',
    'egg': 'ไข่และผลิตภัณฑ์',
    'fish': 'ปลาและผลิตภัณฑ์',
    'peanut': 'ถั่วลิสงและผลิตภัณฑ์',
    'soy': 'ถั่วเหลืองและผลิตภัณฑ์',
    'milk': 'นมและผลิตภัณฑ์ รวมถึงแลคโตส',
    'tree_nuts': 'ถั่วที่มีเปลือกแข็งและผลิตภัณฑ์',
    'sulphites': 'ซัลไฟต์ตั้งแต่ 10 มิลลิกรัมต่อกิโลกรัม',
    'molluscs': 'หอย หมึก และผลิตภัณฑ์',
}
EXTRA_CONSTRAINT_LABELS = {
    'beef': 'เนื้อวัว (ข้อจำกัดเพิ่มเติม)',
    'chicken': 'ไก่ (ข้อจำกัดเพิ่มเติม)',
    'sesame': 'งา (ข้อจำกัดเพิ่มเติม)',
    'pork': 'หมู (ข้อจำกัดเพิ่มเติม)',
    'seafood': 'อาหารทะเล (กลุ่มข้อจำกัดเพิ่มเติม)',
    'echinoderm': 'หอยเม่น/อูนิ (echinoderm; ข้อจำกัดเพิ่มเติม)',
}
THAI_MAPPING_COLUMNS = (
    'allergen_display_th','thai_allergen_10_unverified','thai_law_reference',
    'mapping_audit_note','recommended_thai_allergen_10_unverified',
    *(f'thai_allergen_{tag}' for tag in THAI_ALLERGEN_GROUPS),
)


def mapped_fields(row):
    """Conservative mapping: reported tags are possible; unreported means unknown.

    Never consume the name-only recommended mapping as permission to remove
    recipe tags. In particular, no blank/unknown cell means allergen-free.
    """
    tags={tag.strip() for tag in row.get('allergen_tags','').split(';') if tag.strip()}
    labels={**THAI_ALLERGEN_GROUPS,**EXTRA_CONSTRAINT_LABELS}
    groups=[label for tag,label in THAI_ALLERGEN_GROUPS.items() if tag in tags]
    return {
        'allergen_display_th': '; '.join(labels.get(tag,tag) for tag in sorted(tags)) or 'ยังไม่ทราบ',
        'thai_allergen_10_unverified': '; '.join(groups) or 'ยังไม่ทราบ ไม่ใช่การยืนยันว่าไม่มีสารก่อภูมิแพ้',
        'thai_law_reference':row.get('thai_law_reference') or THAI_LAW_REFERENCE,
        **{f'thai_allergen_{tag}':'possible' if tag in tags else 'unknown' for tag in THAI_ALLERGEN_GROUPS},
    }


if __name__=='__main__':
    import json
    print(json.dumps({'reference':THAI_LAW_REFERENCE,'reference_url':THAI_LAW_URL,
                      'reference_verification':'Reference supplied with audit CSV; recipe evidence is separate',
                      'scope':'packaged-food group registry, not verified restaurant recipes',
                      'groups':THAI_ALLERGEN_GROUPS,'additional_constraints':EXTRA_CONSTRAINT_LABELS,
                      'cell_values':{'possible':'reported tag, unverified recipe/threshold',
                                     'unknown':'not reported; never means absent'}},ensure_ascii=False,indent=2))
