"""Consumer-facing copy. Diagnostics and policy evidence stay in backend reports."""

ALLERGY_WARNING = (
    '⚠️ ผู้แพ้อาหาร: แจ้งพนักงานและยืนยันส่วนผสมก่อนรับประทานทุกครั้ง '
    'ยังมีความเสี่ยงจากส่วนผสมที่ไม่ระบุและการปนเปื้อนข้าม'
)
CLOSING_MESSAGE = 'ขอให้เป็นมื้ออาหารที่อร่อยครับ 🍣 หากต้องการเพิ่มเติม กรุณากด «รีเซ็ตคำถาม» เพื่อเริ่มการสนทนาใหม่'
MENU_NOTICE = 'ราคาและส่วนผสมอาจเปลี่ยนแปลง กรุณายืนยันกับร้านก่อนสั่งอาหาร'

def render_menu(result):
    lines=['🍣 **ชุดเมนูสำหรับคุณ**', '']
    lines.extend(f"- {row['name_th']} × {row['quantity']} — {row['subtotal_baht']:,.2f} บาท"
                 for row in result['selected'])
    lines.extend(['', f"**รวม {result['item_count']} รายการ · {result['total_price']:,.2f} บาท**"])
    spent=result['food_total_price'] if result['drinks_separate_from_budget'] else result['total_price']
    remaining=max(0,round(result['budget']-spent,2))
    lines.extend(['',f"งบ {result['budget']:,.2f} บาท · ใช้ {spent:,.2f} บาท · เหลือ {remaining:,.2f} บาท"])
    target=result.get('spend_target',result['budget'])
    if spent < target*0.95:
        limit=result.get('constraints',{}).get('max_items')
        reason=(f'เพดาน {limit} รายการ และ ' if limit is not None and result['item_count']>=limit else '')
        lines.extend(['','ยังจัดให้ใกล้งบกว่านี้ไม่ได้ภายใต้'+reason+'ข้อจำกัดเมนูและการซ้ำเมนู '
                      'ปรับจำนวนหรือรายการที่ต้องการได้ โดยยังคงข้อจำกัดการแพ้เดิม'])
    if result['drinks_separate_from_budget']:
        net=round(result['budget']-result['total_price'],2)
        lines.append(f"เทียบงบรวมเดิม คงเหลือ {net:,.2f} บาท หลังรวมรายการที่คิดเพิ่ม")
        lines.append(f"ค่าอาหาร {result['food_total_price']:,.2f} บาท · เครื่องดื่มและของหวานคิดเพิ่มนอกงบ")
    if result.get('data_mode')=='simulation':
        lines.extend(['', '🧑‍🍳 ชุดทดลองเพื่อช่วยวางแผนมื้ออาหาร ยังไม่ใช่การสั่งซื้อ'])
    if result.get('allergens_requested'):
        lines.extend(['', ALLERGY_WARNING])
    else:
        lines.extend(['', MENU_NOTICE])
    return '\n'.join(lines)
