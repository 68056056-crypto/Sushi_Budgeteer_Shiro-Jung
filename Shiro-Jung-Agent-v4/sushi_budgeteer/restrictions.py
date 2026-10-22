"""Deterministic Thai refusal rules, independent of the extraction model.

Explicit refusals are hard constraints; dislike wording alone is a soft preference.
Unknown food names are preserved verbatim rather than silently ignored.
"""
import re
from .dietary import exclusion_tags

_ALIASES={'เนื้อหมู':'หมู','pork':'หมู','chicken':'ไก่','beef':'เนื้อวัว',
          'อาหารดิบ':'ดิบ','ของดิบ':'ดิบ','raw':'ดิบ'}
_HARD=r'ไม่กิน|ไม่ทาน|(?:(?<=และ)|(?<![ก-๙A-Za-z]))งด|ห้าม(?:มี|กิน|ทาน)?'
_SOFT=r'(?:ไม่ค่อยชอบ|ไม่ชอบ)(?:กิน|ทาน)?'
# A subsequent intention starts a new clause, including Thai text without spaces.
_STOP=r'(?='+_HARD+r'|เงื่อนไขอื่น|เงื่อนไขเดิม|เหมือนเดิม|ตามเดิม|ไม่ค่อยชอบ|ไม่ชอบ|(?:ไม่ได้|ไม่เคย|ไม่|ไม่มีอาการ|ไม่มี)\s*แพ้|แพ้|ชอบ|อยาก|ต้องการ|งบ|รับของหวาน|ไม่รับ|ไม่เอา|(?:\d+\s*(?:คน|บาท))|[,;.!?\n]|$)'


def canonical_food(value):
    value=str(value).strip().lower()
    return _ALIASES.get(value,value)


def same_food(left,right):
    left,right=canonical_food(left),canonical_food(right)
    return left==right or bool(exclusion_tags(left) and exclusion_tags(left)==exclusion_tags(right))


def _foods(message, trigger):
    found=[]
    for match in re.finditer(r'(?:'+trigger+r')\s*(.*?)'+_STOP,message):
        # "ไม่ได้งด..." and "ไม่ต้องห้าม..." are not positive refusals.
        if re.search(r'(?:ไม่ได้|ไม่ต้อง|ยกเลิก)\s*$',message[:match.start()]):
            continue
        for food in re.split(r'\s*(?:และ|แต่|กับ|หรือ|/)\s*|\s+',match.group(1)):
            food=re.sub(r'(?:เลย|เด็ดขาด|นะครับ|นะคะ|ครับ|ค่ะ|คะ)$','',food).strip()
            if food:
                found.append(canonical_food(food))
    return list(dict.fromkeys(found))


def enforce_restrictions(extracted,message):
    hard=_foods(message,_HARD)
    soft=_foods(message,_SOFT)
    result=dict(extracted)
    # Explicit soft wording corrects a model's invented hard constraint in this turn.
    result['hard_exclude_keywords']=[word for word in result.get('hard_exclude_keywords',[])
        if not any(same_food(word,s) for s in soft) or any(same_food(word,h) for h in hard)]
    for food in hard:
        if not any(same_food(food,word) for word in result['hard_exclude_keywords']):
            result['hard_exclude_keywords'].append(food)
    result['dislikes']=[word for word in result.get('dislikes',[])
                       if not any(same_food(word,h) for h in hard)]
    for food in soft:
        if not any(same_food(food,h) for h in hard) and not any(same_food(food,w) for w in result['dislikes']):
            result['dislikes'].append(food)
    return result
