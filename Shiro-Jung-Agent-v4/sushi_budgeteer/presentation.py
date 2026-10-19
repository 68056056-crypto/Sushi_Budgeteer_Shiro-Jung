"""Consumer-facing copy. Diagnostics and policy evidence stay in backend reports."""

ALLERGY_WARNING = (
    '⚠️ ผู้แพ้อาหาร: แจ้งพนักงานและยืนยันส่วนผสมก่อนรับประทานทุกครั้ง '
    'ยังมีความเสี่ยงจากส่วนผสมที่ไม่ระบุและการปนเปื้อนข้าม'
)
MENU_NOTICE = 'ราคาและส่วนผสมอาจเปลี่ยนแปลง กรุณายืนยันกับร้านก่อนสั่งอาหาร'

def render_menu(result):
    lines=['🍣 **ชุดเมนูสำหรับคุณ**', '']
    lines.extend(f"- {row['name_th']} × {row['quantity']} — {row['subtotal_baht']:,.2f} บาท"
                 for row in result['selected'])
    lines.extend(['', f"**รวม {result['item_count']} รายการ · {result['total_price']:,.2f} บาท**"])
    if result['drinks_separate_from_budget']:
        lines.append(f"ค่าอาหาร {result['food_total_price']:,.2f} บาท · เครื่องดื่มและของหวานคิดเพิ่มนอกงบ")
    if result.get('data_mode')=='simulation':
        lines.extend(['', '🧑‍🍳 ชุดทดลองเพื่อช่วยวางแผนมื้ออาหาร ยังไม่ใช่การสั่งซื้อ'])
    if result.get('allergens_requested'):
        lines.extend(['', ALLERGY_WARNING])
    else:
        lines.extend(['', MENU_NOTICE])
    return '\n'.join(lines)
