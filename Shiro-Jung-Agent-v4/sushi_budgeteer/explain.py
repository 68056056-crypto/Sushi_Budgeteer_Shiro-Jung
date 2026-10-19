"""Deterministic recommendation evidence derived from the same scoring and SQLite rows."""
from .optimizer import score_components, matches_any_keyword

def explain(result, menu):
    constraints=result['constraints'];catalog={x['item_id']:x for x in menu}
    lines=[]
    for selected in result['selected']:
        item=catalog[selected['item_id']]
        food=item['category'] not in {'เครื่องดื่ม','ของหวาน'}
        components=score_components(item,constraints.get('preferred_keywords'),
            is_disliked=matches_any_keyword(item,constraints.get('dislikes',[]))) if food else None
        lines.append({'item_id':item['item_id'],'name':item['name_th'],'quantity':selected['quantity'],
            'unit_price':item['price_baht'],'subtotal':selected['subtotal_baht'],
            'selection_method':'DP: ใกล้วงเงินจัดชุดและลดคะแนนเมนูซ้ำเพื่อความหลากหลาย' if food else 'ตัวเลือกและจำนวนที่ผู้ใช้ระบุ',
            'score_components':components,'source_url':item.get('source_url',''),
            'price_status':item['price_status'],'allergen_status':item['allergen_status'],
            'allergen_tags':item['allergens_verified'],'allergen_source_url':item.get('allergen_source_url',''),
            'checked_at':item.get('checked_at','')})
    return {'objective':'target 95–100% of usable food budget then maximize diminishing-repeat preference score and spend; otherwise maximize spend then score',
        'budget':constraints['budget'],'budget_mode':'food_only' if constraints['drinks_separate_from_budget'] else 'all_items',
        'budget_remaining':round(constraints['budget']-(result['food_total_price'] if constraints['drinks_separate_from_budget'] else result['total_price']),2),
        'catalog_revision':result['catalog_revision'],'data_source':'SQLite imported from local CSV',
        'mode':result['data_mode'],'items':lines,
        'optimization_score_total':result.get('selection_score_total'),
        'spend_target':result.get('spend_target',constraints['budget']),
        'reserved_budget':result.get('reserved_budget',0),
        'food_score_total':round(sum(x['quantity']*x['score_components']['total'] for x in lines if x['score_components']),3),
        'distinct_dishes':result['distinct_dish_count'],'constraints':constraints,
        'unverified_price_items':sum(x['price_status']!='confirmed' for x in lines),
        'unknown_allergen_items':sum(x['allergen_status']!='confirmed' for x in lines)}
