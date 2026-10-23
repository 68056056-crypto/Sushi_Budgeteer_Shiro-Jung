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


def order_aliases(rows, category=None):
    rows=[row for row in rows if row['category'] in {'เครื่องดื่ม','ของหวาน'}]
    ids={row['item_id'] for row in rows}
    aliases={normalize(row['name_th']):[row['item_id']] for row in rows}
    for alias,key in {'โมจิ':'D002','วาราบิ':'D002','วาราบี':'D002','พุดดิ้ง':'D004','ไอศกรีมชาเขียว':'D001',
                      'ชาเขียว':'B001','ลาเต้':'B003','มัทฉะลาเต้เย็น':'B003','ชีสเค้ก':'D003','ซอร์เบต์องุ่น':'D005',
                      'น้ำเปล่า':'B005'}.items():
        if key in ids:
            aliases[normalize(alias)]=[key]
    # Resolve the short name using the menu the customer is viewing.
    if category=='ของหวาน' and 'D001' in ids:
        aliases['ชาเขียว']=['D001']
    ice_creams=[row['item_id'] for row in rows if 'ไอศกรีม' in normalize(row['name_th'])]
    if ice_creams:
        aliases['ไอศกรีม']=ice_creams
    return aliases


def parse_order(message, rows, category=None):
    aliases=order_aliases(rows,category)
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
    remainder=re.sub(r'เลือก|เพิ่ม|สั่ง|เอา|ขอ|รับ|ครับ|ค่ะ|และ|กับ|[,;+\s]','',remainder)
    return {'orders':orders,'ambiguous':ambiguous} if (orders or ambiguous) and not remainder else None


def unavailable_order_names(message,rows,category=None,allow_name_only=False):
    """Validate complete name/quantity orders, with no provider or name-specific rules.

    Unknown and valid items in the same message are rejected atomically. Invalid
    quantity syntax is left to the existing quantity flow, never called unavailable.
    """
    text=normalize(message).strip()
    if re.search(r'งบ|แพ้|ไม่กิน|ไม่ทาน|ไม่ชอบ|ราคา|กี่บาท|เท่าไหร่|อย่างน้อย|ไม่เกิน',text):
        return []
    if text in {'ของหวาน','ขนม','เครื่องดื่ม','น้ำ','รับของหวาน','รับเครื่องดื่ม','รับน้ำ'}:
        return []
    if text.startswith(('ยกเลิก','ไม่เอา','ไม่รับ','เปลี่ยน')):
        return []
    text=re.sub(r'^(?:เลือก|เพิ่ม|สั่ง|เอา|ขอ(?!ง)|รับ)\s*','',text)
    if allow_name_only and not re.search(r'\d|เมนู|อยาก|ใส่|ต้องมี|ดู',text) and text not in {'ของหวาน','ขนม','เครื่องดื่ม','น้ำ','ยืนยัน','ยืนยันรายการทั้งหมด','สรุป','สรุปรายการ','ยอดรวม','ตกลง','ถูกต้อง'}:
        from .menu_matching import exact_match
        name=re.sub(r'(?:ด้วย|ครับ|ค่ะ)$','',text).strip()
        if name and name not in order_aliases(rows,category) and not any(exact_match(row,name) for row in rows):
            return [name]
    parts=list(re.finditer(r'([^\d,;+]+?)\s*(?:x|×)?\s*(\d+)\s*(?:แก้ว|ชิ้น|จาน|รายการ|ถ้วย|ลูก)?',text))
    rest=re.sub(r'([^\d,;+]+?)\s*(?:x|×)?\s*(\d+)\s*(?:แก้ว|ชิ้น|จาน|รายการ|ถ้วย|ลูก)?','',text)
    if not parts or re.sub(r'ครับ|ค่ะ|และ|กับ|[,;+\s]','',rest):
        return []
    from .menu_matching import exact_match
    known=order_aliases(rows,category)
    unknown=[]
    for part in parts:
        name=re.sub(r'^(?:และ|กับ|เลือก|เพิ่ม|สั่ง|เอา|ขอ|รับ)\s*','',part[1].strip()).strip()
        if not re.search(r'[^\W\d_]',name,re.UNICODE) or not 1<=int(part[2])<=60: return []
        if name not in known and not any(exact_match(row,name) for row in rows):
            unknown.append(name)
    return list(dict.fromkeys(unknown))
