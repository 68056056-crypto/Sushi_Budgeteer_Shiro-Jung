"""Deterministic policy enforcement independent of the LLM."""
from __future__ import annotations
import os
from .database import cents, catalog_revision, budget_target_cents

DISCLAIMER = ('ข้อมูลจำลองเพื่อการศึกษา ราคาและสารก่อภูมิแพ้ยังไม่ได้รับรองจากร้าน '
              'ไม่รับประกันการปนเปื้อนจริง ผู้แพ้อาหารต้องตรวจสอบกับพนักงานร้านโดยตรง')

def data_mode():
    mode=os.getenv('SUSHI_DATA_MODE','strict')
    if mode not in {'strict','simulation'}:
        raise ValueError('SUSHI_DATA_MODE ต้องเป็น strict หรือ simulation')
    return mode

def validate_result(result, menu, constraints=None, mode=None):
    mode = data_mode() if mode is None else mode
    if mode not in {"strict", "simulation"}:
        raise ValueError("invalid data mode")
    from .optimizer import matches_any_keyword, parse_allergen_tags
    issues=list(result.get('preflight_issues',[]))
    constraints=constraints or result.get('constraints',{})
    if not constraints:
        return {'passed':False,'issues':['ไม่มี trusted constraint snapshot']}
    from .state import KNOWN_ALLERGENS
    requested={str(x).strip().lower() for x in constraints.get('allergens',[])}
    if requested - KNOWN_ALLERGENS:
        issues.append('มี allergen ที่ยังไม่รู้จัก ต้องตรวจ mapping/หลักฐานเพิ่มเติมก่อน')
    catalog={x['item_id']:x for x in menu}
    if result.get('catalog_revision') != catalog_revision(menu):
        issues.append('ฐานข้อมูลเปลี่ยนหลังคำนวณ ต้องจัดชุดใหม่')
    if result.get('data_mode') != mode:
        issues.append('โหมดข้อมูลเปลี่ยน ต้องคำนวณใหม่')
    selected=result.get('selected',[])
    total=food=food_count=count=drinks=desserts=0
    seen=set()
    for line in selected:
        item=catalog.get(line.get('item_id'))
        qty=line.get('quantity')
        if item is None or type(qty) is not int or not 1<=qty<=60 or line.get('item_id') in seen:
            issues.append('รายการ/จำนวนไม่ถูกต้องหรือ item_id ซ้ำ'); continue
        seen.add(line['item_id'])
        if line['item_id'] in constraints.get('excluded_item_ids', []):
            issues.append('รายการอาหารไม่ตรงชุดที่เลือก')
        price=cents(item['price_baht']); subtotal=price*qty
        total+=subtotal; count+=qty
        is_food=item['category'] not in ('เครื่องดื่ม','ของหวาน')
        if is_food:
            food+=subtotal; food_count+=qty
            if qty>3: issues.append('อาหารซ้ำเกิน 3 จาน')
        elif item['category']=='เครื่องดื่ม': drinks+=qty
        else: desserts+=qty
        if cents(line.get('price_baht',-1))!=price or cents(line.get('subtotal_baht',-1))!=subtotal:
            issues.append('ราคา/ยอดต่อเมนูไม่ตรงฐานข้อมูล')
        if line.get('name_th')!=item['name_th'] or line.get('allergens_verified')!=item['allergens_verified']:
            issues.append('รายละเอียดเมนูไม่ตรงฐานข้อมูล')
        allergens=set(requested)
        if 'seafood' in allergens: allergens |= {'fish','crustacean','molluscs'}
        if allergens & parse_allergen_tags(item['allergens_verified']):
            issues.append(f"เมนู {item['name_th']} ขัดกับ allergen")
        if allergens and mode=='strict' and item.get('allergen_status')!='confirmed':
            issues.append(f"เมนู {item['name_th']} ยังไม่มีหลักฐาน allergen รายเมนู")
        if matches_any_keyword(item,constraints.get('hard_exclude_keywords') or []):
            issues.append(f"เมนู {item['name_th']} ขัดข้อห้าม")
        only=constraints.get('must_include_keywords') or []
        if is_food and only and not matches_any_keyword(item,only):
            issues.append('อาหารไม่ตรงเงื่อนไขเอาเฉพาะ')
    if not constraints['min_items']<=count<=constraints['max_items']:
        issues.append('จำนวนรายการไม่อยู่ในช่วงที่ขอ')
    if food_count<1: issues.append('ไม่มีอาหารหลักที่จัดได้ตามข้อจำกัด')
    if constraints.get('checkout_food_limit') is not None:
        if constraints['checkout_food_limit']!=60 or food_count>60 or drinks>60 or desserts>60:
            issues.append('จำนวนอาหารหรือรายการเพิ่มเติมเกินขอบเขต')
    if (food if constraints.get('drinks_separate_from_budget') else total)>cents(constraints['budget']):
        issues.append('ยอดเกินงบ')
    target_limit=budget_target_cents(constraints['budget'],constraints.get('spend_ratio',1.0))
    if (food if constraints.get('drinks_separate_from_budget') else total)>target_limit:
        issues.append('ยอดเกินวงเงินจัดชุดที่กันงบสำรองไว้')
    if 'spend_target' in result and cents(result['spend_target'])!=target_limit:
        issues.append('วงเงินจัดชุดไม่ตรงข้อมูลที่ยืนยัน')
    if 'reserved_budget' in result and cents(result['reserved_budget'])!=cents(constraints['budget'])-target_limit:
        issues.append('งบสำรองไม่ตรงข้อมูลที่ยืนยัน')
    if cents(result.get('total_price',-1))!=total or cents(result.get('food_total_price',-1))!=food:
        issues.append('ยอดรวมไม่ตรงยอดที่คำนวณจากฐานข้อมูล')
    if result.get('item_count')!=count: issues.append('จำนวนรวมไม่ตรงรายการ')
    # Match fixed allocations back to the requested names and trusted catalog.
    from collections import Counter
    from .tools import _resolve_quantity_items
    for category, selection, quantity, per_item in [
        ('เครื่องดื่ม', constraints.get('drink_selection') or [], constraints.get('drink_quantity'), constraints.get('drink_quantities') or None),
        ('ของหวาน', (constraints.get('dessert_selection') or []) if constraints.get('include_dessert') else [], constraints.get('dessert_quantity'), None)]:
        if 'checkout_extras' in constraints:
            plan=constraints['checkout_extras']
            if any(key not in catalog or catalog[key]['category'] not in {'เครื่องดื่ม','ของหวาน'}
                   or type(qty) is not int or not 1<=qty<=60 for key,qty in plan.items()):
                issues.append('รายการเพิ่มเติมที่ยืนยันไม่ถูกต้อง')
            expected_ids=Counter({key:qty for key,qty in plan.items() if key in catalog and catalog[key]['category']==category})
        else:
            expected_items=_resolve_quantity_items(menu,category,selection,
                quantity if quantity is not None else constraints.get('num_people',1), per_item)
            expected_ids=Counter(x['item_id'] for x in expected_items)
        actual_ids=Counter({x['item_id']:x['quantity'] for x in selected
            if x.get('item_id') in catalog and catalog[x['item_id']]['category']==category})
        if actual_ids != expected_ids: issues.append('รายการเครื่องดื่ม/ของหวานไม่ตรงตัวเลือกที่ยืนยัน')
    expected_drinks=constraints.get('drink_quantity')
    if constraints.get('drink_selection'):
        expected_drinks=expected_drinks if expected_drinks is not None else constraints.get('num_people',1)
        if drinks!=expected_drinks: issues.append('จำนวนเครื่องดื่มไม่ตรงที่ขอ')
    if constraints.get('include_dessert'):
        expected=constraints.get('dessert_quantity')
        expected=expected if expected is not None else constraints.get('num_people',1)
        if desserts!=expected: issues.append('จำนวนของหวานไม่ตรงที่ขอ')
    elif desserts: issues.append('ไม่ได้ยืนยันของหวาน')
    facts = policy_facts(result, menu, constraints, issues, mode)
    from .opa import evaluate
    decision = evaluate(facts)
    if not decision['allow']:
        issues.extend('OPA: '+reason for reason in decision['deny_reasons'])
    return {'passed':not issues,'issues':list(dict.fromkeys(issues)), 'policy_decision':decision,
            'policy_input':facts,
            'recomputed_total':total/100,'recomputed_food_total':food/100,
            'catalog_revision':catalog_revision(menu),'disclaimer':DISCLAIMER}


def policy_facts(result, menu, constraints, issues, mode=None):
    """Build facts only from trusted catalog and server-held constraints, never model claims."""
    from .optimizer import matches_any_keyword, parse_allergen_tags
    catalog={x['item_id']:x for x in menu}
    allergens={str(x).lower().strip() for x in constraints.get('allergens',[])}
    if 'seafood' in allergens: allergens |= {'fish','crustacean','molluscs'}
    lines=[]
    for line in result.get('selected',[]):
        item=catalog.get(line.get('item_id'),{})
        food=item.get('category') not in {'เครื่องดื่ม','ของหวาน'}
        only=constraints.get('must_include_keywords',[])
        lines.append({'item_id':line.get('item_id'),'quantity':line.get('quantity',0),
            'catalog_item':bool(item),'food':food,'unit_cents':cents(item.get('price_baht',0)),
            'reported_unit_cents':cents(line.get('price_baht',0)),
            'reported_subtotal_cents':cents(line.get('subtotal_baht',0)),
            'allergen_blocked':bool(allergens & parse_allergen_tags(item.get('allergens_verified'))),
            'evidence_confirmed':item.get('allergen_status')=='confirmed',
            'hard_excluded':matches_any_keyword(item,constraints.get('hard_exclude_keywords',[])),
            'only_allowed':not only or matches_any_keyword(item,only)})
    return {'schema_version':1,'lines':lines,'python_issues':list(issues),
        'checkout':constraints.get('checkout_food_limit')==60,
        'drinks_count':sum(line['quantity'] for line in selected_lines(result,menu,'เครื่องดื่ม')),
        'desserts_count':sum(line['quantity'] for line in selected_lines(result,menu,'ของหวาน')),
        'budget_cents':cents(constraints['budget']),
        'total_cents':cents(result.get('total_price',0)),
        'food_cents':cents(result.get('food_total_price',0)),
        'count':result.get('item_count',0),
        'food_count':sum(x['quantity'] for x in lines if x['food']),
        'min_items':constraints['min_items'],'max_items':constraints['max_items'],
        'allergy_requested':bool(allergens),'data_mode':data_mode() if mode is None else mode,
        'separate_budget':bool(constraints.get('drinks_separate_from_budget')),
        'catalog_revision':catalog_revision(menu),'result_catalog_revision':result.get('catalog_revision','')}


def selected_lines(result, menu, category):
    ids={row['item_id'] for row in menu if row['category']==category}
    return [row for row in result.get('selected',[]) if row.get('item_id') in ids]
