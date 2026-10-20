"""Deterministic short menu names + quantities; units are optional."""
import re
import unicodedata


def normalize(text):
    text=unicodedata.normalize('NFKC',text).lower()
    text=text.replace('ํ้า','้ำ').replace('ํา','ำ')
    text=text.translate(str.maketrans('๐๑๒๓๔๕๖๗๘๙','0123456789'))
    text=re.sub('[\u200b\u200c\u200d\ufeff]','',text)
    text=text.replace('ไอติม','ไอศกรีม')
    text=re.sub(r'ไอ(?:ศ|ส|ศก|ศะ|ศะก|ศค|สก)?ค?รีม','ไอศกรีม',text)
    return text


def parse_order(message, rows):
    rows=[row for row in rows if row['category'] in {'เครื่องดื่ม','ของหวาน'}]
    ids={row['item_id'] for row in rows}
    aliases={normalize(row['name_th']):[row['item_id']] for row in rows}
    for alias,key in {'โมจิ':'D002','พุดดิ้ง':'D004','ไอศกรีมชาเขียว':'D001',
                      'ชาเขียว':'B001','ลาเต้':'B003','ชีสเค้ก':'D003','ซอร์เบต์องุ่น':'D005',
                      'น้ำเปล่า':'B005'}.items():
        if key in ids:
            aliases[normalize(alias)]=[key]
    ice_creams=[row['item_id'] for row in rows if 'ไอศกรีม' in normalize(row['name_th'])]
    if ice_creams:
        aliases['ไอศกรีม']=ice_creams
    if not aliases:
        return None
    pattern='|'.join(re.escape(name) for name in sorted(aliases,key=len,reverse=True))
    orders={}
    seen=set()
    ambiguous=[]
    def extract(match):
        candidates=aliases[match.group(1)]
        qty=int(match.group(2))
        if any(key in seen for key in candidates) or not 1<=qty<=60:
            return match.group(0)
        seen.update(candidates)
        if len(candidates)==1:
            orders[candidates[0]]=qty
        else:
            ambiguous.append({'name':match.group(1),'quantity':qty,'candidates':candidates})
        return ' '
    text=normalize(message)
    remainder=re.sub(r'('+pattern+r')\s*(?:x|×)?\s*(\d+)\s*(?:แก้ว|ชิ้น|จาน|รายการ|ถ้วย|ลูก)?',extract,text)
    remainder=re.sub(r'เลือก|เพิ่ม|เอา|ขอ|รับ|ครับ|ค่ะ|และ|กับ|[,;+\s]','',remainder)
    return {'orders':orders,'ambiguous':ambiguous} if (orders or ambiguous) and not remainder else None
