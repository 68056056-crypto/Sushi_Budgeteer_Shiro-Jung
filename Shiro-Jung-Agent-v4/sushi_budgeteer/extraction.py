"""Thai intent extraction prompt and deterministic slot guards."""
from typing import Any, Dict, Optional
import re

_NARROW_SLOT_FIELDS = {
    "num_people", "drinks", "drink_quantity", "drinks_budget_mode",
    "dessert", "dessert_selection", "dessert_quantity",
}
_MUST_INCLUDE_TRIGGERS = ("กินแค่", "เอาเฉพาะ", "only")
_HARD_EXCLUDE_TRIGGERS = ("ไม่กินเลย", "ไม่เอาเลย", "งด", "ห้ามมี")


def _sanitize_extraction(
    extracted: Dict[str, Any], last_asked_field: Optional[str], user_message: str
) -> Dict[str, Any]:
    # A preference is not a medical declaration. Never invent allergies from context.
    positive=re.sub(r'(?:ไม่ได้|ไม่เคย|ไม่|มิได้|ไม่มีอาการ|ไม่มี)\s*แพ้.*?(?=แต่|[,;\n]|$)', '', user_message)
    positive=re.sub(r'\b(?:not allergic|no allerg(?:y|ies))\b.*?(?=but|[,;\n]|$)', '', positive, flags=re.IGNORECASE)
    if not re.search(r'แพ้|\ballerg(?:ic|y|ies)\b', positive, re.IGNORECASE):
        extracted={**extracted,'allergens':[]}
    dislikes=list(extracted.get('dislikes') or [])
    for name in ('ปลาหมึก','แซลมอน','กุ้ง','หอย','ปลา','ไข่','นม','ถั่วเหลือง'):
        term=re.escape(name)+(r'(?!หมึก)' if name=='ปลา' else '')
        if re.search(r'(?:ไม่ค่อยชอบ|ไม่ชอบ)(?:กิน|ทาน)?\s*'+term, user_message) or re.search(
                term+r'(?:เป็น)?(?:แค่)?ไม่ชอบ',user_message):
            if name not in dislikes:
                dislikes.append(name)
    extracted={**extracted,'dislikes':dislikes}
    # Drink names are an order, not a food preference: keep them out of food scoring.
    drink_names = {str(x).strip().lower() for x in (extracted.get("drink_selection") or [])}
    drink_names |= {str(x).strip().lower() for x in (extracted.get("drink_quantities") or {})}
    if drink_names and extracted.get("preferred_keywords"):
        extracted = {**extracted, "preferred_keywords": [
            k for k in extracted["preferred_keywords"] if str(k).strip().lower() not in drink_names]}
    if last_asked_field not in _NARROW_SLOT_FIELDS:
        return extracted
    lowered = user_message.lower()
    if extracted.get("must_include_keywords") and not any(t in lowered for t in _MUST_INCLUDE_TRIGGERS):
        extracted = {**extracted, "must_include_keywords": []}
    if extracted.get("hard_exclude_keywords") and not any(t in lowered for t in _HARD_EXCLUDE_TRIGGERS):
        extracted = {**extracted, "hard_exclude_keywords": []}
    return extracted



EXTRACT_PROMPT = """คุณคือระบบสกัดข้อมูลโครงสร้าง (Intent Extractor) จากข้อความภาษาไทย/อังกฤษ
ของผู้ใช้ระบบจัดเซ็ตเมนูซูชิ
หากมีข้อมูลมื้อเดิมแล้ว ให้สกัดเฉพาะข้อมูลที่ผู้ใช้เปลี่ยน ไม่เริ่มถามข้อมูลเดิมใหม่
"อยากกินเซลมอน" หรือ "อยากทานแซลมอน" คือ preferred_keywords=["แซลมอน"], intent="optimize"
เมื่อผู้ใช้บอกความชอบต่อจากชุดก่อน ให้ปรับชุดเดิม ไม่ใช่ค้นหาเมนู ยกเว้นถามชัดเจนว่า "มีเมนูอะไร" หรือ "ขอดูราคา"
ห้ามเปลี่ยนหรือลบอาการแพ้ที่จำไว้เพียงเพราะผู้ใช้บอกว่าอยากกินเมนูใหม่
"ไม่ชอบปลาหมึก" คือ dislikes=["ปลาหมึก"] เท่านั้น ไม่ใช่ allergens=["molluscs"]
ถ้าผู้ใช้บอก "ไม่ได้แพ้ แค่ไม่ชอบ" อย่าสร้าง allergy ใหม่ ระบบจะให้ยืนยันการแก้ไขเอง
สกัดเฉพาะข้อมูลจากข้อความล่าสุด ไม่คัดลอก allergens จากบริบทมาว่าเป็นการแจ้งใหม่
ห้ามเดา max_items=20 จากค่าเริ่มต้น หากผู้ใช้ไม่ได้กำหนดจำนวนรายการ ให้ max_items=null

อ่านข้อความของผู้ใช้ แล้วคืนค่าเป็น JSON เท่านั้น (ห้ามมีข้อความอื่นนอกเหนือจาก JSON)
ด้วยโครงสร้างดังนี้:
{
  "budget": <number ใหม่แบบเต็มจำนวน หรือ null — ใช้เมื่อผู้ใช้บอกตัวเลขงบใหม่ตรงๆ
    เช่น "งบ 500 บาท", "เปลี่ยนเป็น 300"; ห้ามใช้ฟิลด์นี้กับประโยคที่ขอ "เพิ่ม/ลด"
    งบแบบสัมพัทธ์ (relative) ให้ใช้ budget_delta แทน>,
  "budget_delta": <number บวก(เพิ่ม)/ลบ(ลด) หรือ null — ใช้เมื่อผู้ใช้บอกจำนวนที่
    จะเพิ่ม/ลดจากงบเดิม เช่น "เพิ่มงบอีก 100 บาท" -> 100, "ลดงบลง 50" -> -50>,
  "budget_change_unclear": <true เมื่อผู้ใช้พูดถึงการเพิ่ม/ลด/เปลี่ยนงบประมาณ
    ชัดเจนแต่ "ไม่ได้บอกจำนวนเป็นตัวเลขเลย" เช่น "เพิ่มงบอีกหน่อย", "ลดงบลงหน่อย"
    (ทั้ง budget และ budget_delta จะเป็น null ในกรณีนี้) มิฉะนั้นเป็น false>,
  "allergens": [<string จากกลุ่มนี้เท่านั้น: fish, crustacean, molluscs, egg, milk, gluten, soy, sesame, pork — ใช้เฉพาะการแพ้อาหารจริงทางการแพทย์>],
  "dislikes": [<string keyword ที่ผู้ใช้บอกว่าไม่ค่อยชอบ/เฉยๆ — แค่ลดคะแนน ไม่ตัดออก>],
  "preferred_keywords": [<string keyword ที่ผู้ใช้บอกว่าชอบ/อยากได้ — บวกคะแนนเท่านั้น>],
  "hard_exclude_keywords": [<string คำหลักที่ "สั้นและกระชับที่สุด" ที่น่าจะปรากฏอยู่จริงในชื่อ/หมวดหมู่เมนู เมื่อผู้ใช้บอกว่า "ห้ามมีเลย"/"ไม่กินเด็ดขาด"/"งด" แบบเด็ดขาด แต่ไม่ใช่การแพ้อาหารทางการแพทย์ — ตัดคำฟุ่มเฟือยออก เช่น "ของดิบ" ให้ใช้ "ดิบ", "เนื้อหมู" ให้ใช้ "หมู", "อาหารทะเล" ให้แยกเป็น "กุ้ง","ปู","หอย","ปลา" — ตัดออกทั้งหมดเหมือน allergen>],
  "must_include_keywords": [<string keyword เมื่อผู้ใช้บอกว่า "กินแค่", "เอาเฉพาะ", "only" — ตัดทุกอย่างที่ไม่ตรงกับคำเหล่านี้ออกทั้งหมด>],
  "min_items": <number หรือ null>,
  "max_items": <number หรือ null>,
  "num_people": <number คนที่รับประทาน หรือ null — เช่น "2 คน", "กินกัน 4 คน", "คนเดียว" -> 1>,
  "allergy_check_answered": <true เมื่อข้อความนี้เป็นคำตอบของคำถาม "ไม่ชอบทานอะไร/แพ้อะไรไหม"
    ไม่ว่าคำตอบจะเป็นอะไรก็ตาม รวมถึง "ไม่มี"/"ไม่แพ้อะไร" ด้วย (ต้องถือว่าตอบแล้ว
    ไม่ใช่แค่ตอนที่มี allergens/dislikes เท่านั้น) มิฉะนั้น false>,
  "wants_dessert": <true/false เมื่อผู้ใช้ตอบคำถาม "รับของหวานไหม" อย่างชัดเจน
    (เช่น "เอา"/"รับ" -> true, "ไม่เอา"/"ไม่รับ" -> false) มิฉะนั้น null>,
  "drink_selection": [<string ชื่อเครื่องดื่มที่ผู้ใช้เลือกจากเมนูเครื่องดื่ม
    เช่น "ชาเขียวร้อน", "โค้ก", "น้ำส้ม" เมื่อตอบคำถาม "รับน้ำอะไรบ้าง">],
  "drink_quantities": {<ชื่อเครื่องดื่ม>: <จำนวนแก้ว>} — ใช้เมื่อผู้ใช้บอกจำนวน "แยกแต่ละอย่าง"
    เช่น "ชาเขียว 2 โค้ก 2" -> {"ชาเขียวร้อน": 2, "โค้ก": 2}; คำว่า "ที่เหลือ"/"คนที่เหลือ"
    ให้คำนวณจาก num_people ในบริบท ลบด้วยจำนวนที่ระบุแล้ว เช่น 6 คน "ชาเขียว 2 โค้ก 2
    ที่เหลือน้ำส้ม" -> {"ชาเขียวร้อน": 2, "โค้ก": 2, "น้ำส้ม": 2}; ใช้ชื่อตามที่ผู้ใช้พูด
    แม้ไม่แน่ใจว่ามีในเมนู (ระบบจะตรวจกับฐานข้อมูลเอง) เมื่อใช้ฟิลด์นี้ให้ใส่ชื่อเดียวกันใน
    drink_selection และตั้ง drink_quantity เป็น null; ถ้าไม่ได้แยกจำนวนให้เป็น {}
    ชื่อเครื่องดื่มห้ามใส่ใน preferred_keywords>,
  "drink_quantity": <number จำนวนแก้วเครื่องดื่มที่ผู้ใช้ระบุ หรือ null — เป็นคนละ
    คำถามกับ "รับน้ำอะไรบ้าง" เสมอ (ถามชื่อก่อน แล้วจึงถามจำนวนแยกต่างหาก)>,
  "drinks_budget_mode": <"within" เมื่อผู้ใช้บอกว่าให้รวมค่าเครื่องดื่ม/ของหวาน
    อยู่ในงบเดิม, "separate" เมื่อบอกว่าให้แยกคิดต่างหาก (ไม่รวมในงบ), หรือ null
    ถ้ายังไม่ได้ตอบคำถามนี้>,
  "dessert_selection": [<string ชื่อของหวานที่ผู้ใช้เลือก เมื่อตอบว่ารับของหวาน
    และระบุชนิดด้วย เช่น "โมจิ", "ไอศกรีม">],
  "dessert_quantity": <number จำนวนชิ้นของหวานที่ผู้ใช้ระบุ หรือ null — เป็นคนละ
    คำถามกับ "รับของหวานเมนูไหน" เสมอ (ถามชื่อก่อน แล้วจึงถามจำนวนแยกต่างหาก)>,
  "intent": <หนึ่งใน "optimize", "search", "info", "clarify_answer">
}

หมายเหตุสำคัญ: "ไม่ชอบ" / "เบื่อ" -> dislikes (soft). "ไม่กินเลย" / "ไม่เอาเลย" /
"งด" / "ห้ามมี" ของสิ่งที่ไม่ใช่สารก่อภูมิแพ้ทางการแพทย์ -> hard_exclude_keywords
(hard). "ชอบ" / "อยากได้" -> preferred_keywords (soft). "กินแค่" / "เอาเฉพาะ" /
"only" -> must_include_keywords (hard, ตัดอย่างอื่นออกทั้งหมด).

สำคัญมาก — การตีความข้อความสั้นๆ ตามบริบท: ข้อความของผู้ใช้บางครั้งสั้นมาก
(เช่น "ไม่", "ไม่มี", "ค่ะ", ตัวเลขเดี่ยวๆ, ชื่อเครื่องดื่มเดี่ยวๆ) ซึ่งความหมาย
ขึ้นอยู่กับว่า "ระบบเพิ่งถามอะไรไป" — ถ้าพรอมป์นี้มีบรรทัด
"[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'X']" กำกับไว้ก่อนข้อความผู้ใช้ ให้ตีความ
คำตอบสั้นๆ นั้นโดยอิง X เสมอ:
- X="allergy": คำตอบปฏิเสธ ("ไม่", "ไม่มี", "เปล่า", "ไม่แพ้") -> allergy_check_answered=true
  (allergens/dislikes ปล่อยว่าง); คำตอบที่ระบุของ -> allergy_check_answered=true
  พร้อมใส่ allergens/dislikes ตามที่ระบุ
- X="num_people": ตัวเลขเดี่ยวๆ หรือ "คนเดียว"/"N คน" -> num_people
- X="drinks": ชื่อเครื่องดื่ม หรือ "อะไรก็ได้" -> drink_selection (ใส่ "ชาเขียวร้อน"
  ถ้าตอบว่าอะไรก็ได้)
- X="drink_quantity": ตัวเลขเดี่ยวๆ -> drink_quantity (ห้ามใส่ใน drink_selection)
- X="drinks_budget_mode": "รวม"/"ในงบเดิม" -> drinks_budget_mode="within";
  "แยก"/"ไม่รวม"/"นอกงบ" -> drinks_budget_mode="separate"
- X="dessert": "เอา"/"รับ"/ชื่อของหวาน -> wants_dessert=true (+dessert_selection
  ถ้าระบุชนิด); "ไม่เอา"/"ไม่รับ"/"พอแล้ว" -> wants_dessert=false
- X="dessert_selection": ชื่อของหวาน -> dessert_selection (wants_dessert เป็น
  true อยู่แล้วจากคำถามก่อนหน้า ไม่ต้องตั้งซ้ำ)
- X="dessert_quantity": ตัวเลขเดี่ยวๆ -> dessert_quantity

ตัวอย่าง (ทุกฟิลด์ที่ไม่ได้พูดถึงในข้อความให้เป็นค่า default: null/false/[]):
ข้อความ: "จัดเซ็ตงบ 300 บาท แพ้กุ้ง ชอบแซลมอน"
JSON: {"budget": 300, "budget_delta": null, "budget_change_unclear": false, "allergens": ["crustacean"], "dislikes": [], "preferred_keywords": ["แซลมอน"], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "แพ้ปลาด้วยนะ"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": ["fish"], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "งบ 1000 กินแค่กุ้งกับปลา ไม่กินของดิบเลย"
JSON: {"budget": 1000, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": ["ดิบ"], "must_include_keywords": ["กุ้ง", "ปลา"], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "ไม่ชอบหอยเท่าไหร่"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": ["หอย"], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "เพิ่มงบอีก 100 บาท"
JSON: {"budget": null, "budget_delta": 100, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "optimize"}

ข้อความ: "เพิ่มงบประมาณอีกหน่อย" (ไม่มีตัวเลขเลย)
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": true, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'num_people']\nกินกัน 3 คน"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": 3, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'allergy']\nไม่มีค่ะ ไม่แพ้อะไร"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": true, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'allergy']\nไม่" (สั้นมาก แต่บริบทบอกว่ากำลังตอบคำถามแพ้อาหาร — ต้องตีความว่าตอบแล้วว่าไม่มี)
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": true, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drinks']\nรับชาเขียวร้อนค่ะ"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": ["ชาเขียวร้อน"], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drinks'; บริบท num_people=6]\nชาเขียวร้อน 2 โค้ก 2 ที่เหลือน้ำส้ม"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": ["ชาเขียวร้อน", "โค้ก", "น้ำส้ม"], "drink_quantities": {"ชาเขียวร้อน": 2, "โค้ก": 2, "น้ำส้ม": 2}, "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drink_quantity']\n2 แก้ว"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": 2, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'drinks_budget_mode']\nรวมในงบเดิมได้เลย"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": "within", "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'dessert']\nเอาของหวานด้วย เอาโมจิ"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": true, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": ["โมจิ"], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'dessert']\nไม่เอา"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": false, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": null, "intent": "clarify_answer"}

ข้อความ: "[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง 'dessert_quantity']\n3 ชิ้น"
JSON: {"budget": null, "budget_delta": null, "budget_change_unclear": false, "allergens": [], "dislikes": [], "preferred_keywords": [], "hard_exclude_keywords": [], "must_include_keywords": [], "min_items": null, "max_items": null, "num_people": null, "allergy_check_answered": false, "wants_dessert": null, "drink_selection": [], "drink_quantity": null, "drinks_budget_mode": null, "dessert_selection": [], "dessert_quantity": 3, "intent": "clarify_answer"}"""



def contextual_answer(last_asked_field, message):
    """Handle exact button/short replies only; richer messages still use extraction."""
    text=message.strip().lower()
    if text in {'ไม่รับของหวาน','ไม่เอาของหวาน','ไม่รับขอหวาน','ไม่เอาขอหวาน'}:
        return {'wants_dessert':False}
    no={'ไม่','ไม่มี','ไม่เอา','ไม่รับ','ไม่รับของหวาน','ไม่แพ้','ไม่แพ้อะไร','ไม่มีค่ะ','ไม่มีครับ'}
    if last_asked_field=='allergy' and text in no:
        return {'allergy_check_answered':True}
    if last_asked_field=='dessert':
        if text in no:
            return {'wants_dessert':False}
        if text in {'รับ','เอา','รับของหวาน','เอาของหวาน'}:
            return {'wants_dessert':True}
    if last_asked_field=='drinks_budget_mode':
        if text in {'รวม','รวมในงบ','ในงบเดิม','รวมในงบเดิม'}:
            return {'drinks_budget_mode':'within'}
        if text in {'แยก','คิดแยก','นอกงบ','คิดแยกนอกงบ'}:
            return {'drinks_budget_mode':'separate'}
    if text.isdecimal() and last_asked_field in {'budget','num_people','drink_quantity','dessert_quantity'}:
        return {last_asked_field:int(text)}
    return None


ALLERGEN_ALIASES={
    'molluscs':('ปลาหมึก','หมึก','หอย'), 'crustacean':('กุ้ง','ปู'),
    'fish':('ปลา','แซลมอน'), 'egg':('ไข่',), 'milk':('นม',),
    'soy':('ถั่วเหลือง','ซีอิ๊ว'), 'gluten':('กลูเตน','แป้งสาลี'),
    'sesame':('งา',), 'peanut':('ถั่วลิสง',), 'tree_nuts':('ถั่วเปลือกแข็ง',),
    'seafood':('อาหารทะเล',), 'pork':('หมู',), 'sulphites':('ซัลไฟต์',)}


def requested_allergy_corrections(message, current_allergens):
    """Propose removals only for an explicit user correction, applied after confirmation."""
    if not re.search(r'(?:ไม่ได้|ไม่เคย|ไม่|มิได้)\s*แพ้',message):
        return []
    if message.strip() in {'ไม่แพ้','ไม่แพ้อะไร','ไม่ได้แพ้อาหาร','ไม่แพ้อาหาร'}:
        return list(current_allergens)
    # Prefer specific shellfish words over the generic Thai word for fish.
    mentioned=[tag for tag in current_allergens
               if any(alias in message for alias in ALLERGEN_ALIASES.get(tag,(tag,)))]
    if 'ปลาหมึก' in message and 'molluscs' in mentioned:
        mentioned=[tag for tag in mentioned if tag!='fish']
    return mentioned
