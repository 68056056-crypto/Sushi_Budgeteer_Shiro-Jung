"""One contextual choice for ambiguous land-animal meat, preserving relation type."""
import re

MEAT_CHOICES={'หมู':['pork'],'เนื้อวัว':['beef'],'ไก่':['chicken'],
              'สัตว์บกทั้งหมด':['pork','beef','chicken']}
MEAT_WORDS={'pork':'หมู','beef':'เนื้อวัว','chicken':'ไก่'}
GENERIC_WORDS={'เนื้อ','เนื้อสัตว์','เนื้อสัตว์บก','meat','หมู','เนื้อหมู','pork','วัว','เนื้อวัว','beef','ไก่','chicken'}


def meat_relation(message):
    match=re.search(r'(ไม่ชอบ|ไม่กิน|ไม่ทาน|ไม่เอา|งด|ห้าม(?:มี|กิน|ทาน)?|แพ้)\s*เนื้อ(?:สัตว์(?:บก)?)?(?=$|[\s,;.?!]|เลย|เด็ดขาด|ครับ|ค่ะ|และ|แต่|กับ)',message)
    if not match:
        return None
    if match.group(1)=='แพ้' and re.search(r'(?:ไม่|ไม่ได้|ไม่เคย)\s*$',message[:match.start()]):
        return None
    return {'ไม่ชอบ':'dislikes','แพ้':'allergens'}.get(match.group(1),'hard_exclude_keywords')


def defer_meat_guess(extracted, message):
    kind=meat_relation(message)
    if not kind:
        return extracted
    result=dict(extracted)
    result[kind]=[word for word in result.get(kind,[]) if str(word).strip().lower() not in GENERIC_WORDS]
    return result
