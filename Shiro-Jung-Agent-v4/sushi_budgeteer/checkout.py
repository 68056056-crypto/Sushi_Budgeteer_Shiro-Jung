"""Catalog-backed extras, immutable food selection and revalidated checkout.

This mixin uses the owning Agent's per-session constraints and safety mode.
"""
from __future__ import annotations
import copy
import logging
import re
from uuid import uuid4
from .dietary import ingredient_allergens, hard_excluded
from .presentation import CLOSING_MESSAGE
LOG=logging.getLogger('shiro_jung.agent')

class CheckoutMixin:
    def extra_items(self, category):
        """Read selectable extras using this session's safety mode, without global mutation."""
        from .database import records
        from .state import KNOWN_ALLERGENS
        if category not in {'เครื่องดื่ม','ของหวาน'}:
            return []
        allergens=set(self.state.allergens)
        if allergens-KNOWN_ALLERGENS:
            return []
        if 'seafood' in allergens:
            allergens|={'fish','crustacean','molluscs','echinoderm'}
        return [row for row in records() if row['category']==category
                and not allergens & ingredient_allergens(row)
                and not hard_excluded(row,self.state.hard_exclude_keywords)
                and not (allergens and self.data_mode=='strict' and row.get('allergen_status')!='confirmed')]


    def open_extras(self, category):
        if self.order_closed:
            return CLOSING_MESSAGE
        self.extra_category=category
        if self.food_choice is not None:
            self.checkout_step='drinks_menu' if category=='เครื่องดื่ม' else 'desserts_menu'
        self.pending_confirmation=False
        items=self.extra_items(category)
        if not items:
            return 'ยังไม่มี'+category+'ที่เลือกได้ตามข้อจำกัดของคุณครับ กรุณาตรวจส่วนผสมกับพนักงานร้านก่อน'
        return ('**เมนู'+category+' 🍵**\n\n'
                +'\n'.join(f"- {row['name_th']} — {row['price_baht']:,.2f} บาท" for row in items)
                +'\n\nพิมพ์ชื่อย่อพร้อมจำนวน เช่น '+('น้ำส้ม 2 ชาเขียว 1' if category=='เครื่องดื่ม' else 'โมจิ 2')+' ได้เลยครับ ไม่ต้องใส่หน่วย')


    def choose_extra(self, item_id, quantity):
        """Canonical item/quantity from the picker; normal confirmation and checks still apply."""
        if self.order_closed:
            return CLOSING_MESSAGE
        if type(quantity) is not int or not 1<=quantity<=60:
            return 'กรุณาเลือกจำนวน 1–60 ครับ'
        row=next((r for r in self.extra_items(self.extra_category) if r['item_id']==item_id),None)
        if row is None:
            return 'เมนูนี้เลือกไม่ได้แล้ว กรุณาเปิดรายการใหม่ครับ'
        if self.extra_category=='ของหวาน':
            update={'wants_dessert':True,'dessert_selection':[row['name_th']],'dessert_quantity':quantity}
        else:
            update={'drink_selection':[row['name_th']],'drink_quantities':{row['name_th']:quantity},'drink_quantity':quantity}
        if self.food_choice is not None:
            return self.set_checkout_extras({item_id:quantity})
        # Feed a validated selection through the existing intake path without a model extraction.
        self._picker_update=update
        self.extra_category=None
        try:
            return self.chat(f"เลือก {row['name_th']} {quantity} รายการ")
        finally:
            self._picker_update=None


    def set_checkout_extras(self, quantities):
        """Upsert exact quantities per item; repeated messages never double-add an item."""
        available={row['item_id']:row for category in ('เครื่องดื่ม','ของหวาน') for row in self.extra_items(category)}
        if not quantities or any(key not in available or type(qty) is not int or not 1<=qty<=60
                                 for key,qty in quantities.items()):
            return 'ยังเพิ่มไม่ได้ครับ กรุณาบอกชื่อจากเมนูและจำนวน 1–60 ต่อรายการ'
        self.extras_plan.update(quantities)
        self.sync_checkout_extras()
        return self.checkout_summary()


    def sync_checkout_extras(self):
        from .database import records
        catalog={row['item_id']:row for row in records()}
        drinks={catalog[key]['name_th']:qty for key,qty in self.extras_plan.items()
                if key in catalog and catalog[key]['category']=='เครื่องดื่ม'}
        desserts={catalog[key]['name_th']:qty for key,qty in self.extras_plan.items()
                  if key in catalog and catalog[key]['category']=='ของหวาน'}
        self.state.drink_selection=list(drinks)
        self.state.drink_quantities=drinks
        self.state.drink_quantity=sum(drinks.values()) if drinks else None
        self.state.dessert_selection=list(desserts)
        self.state.dessert_quantity=sum(desserts.values()) if desserts else None
        self.state.wants_dessert=bool(desserts)


    def parse_extra_quantities(self, message):
        from .database import records
        from .extra_order import parse_order
        parsed=parse_order(message,records(),category=self.extra_category)
        return parsed['orders'] if parsed and not parsed['ambiguous'] else None


    def extra_choice_prompt(self):
        from .database import records
        pending=self.pending_extra_order['ambiguous'][0]
        catalog={row['item_id']:row for row in records()}
        rows=[catalog[key] for key in pending['candidates'] if key in catalog]
        return (f"รับทราบ {pending['name']} {pending['quantity']} ชิ้นครับ เลือกชนิดอีกนิดเดียว:\n\n"
                +'\n'.join(f"{index+1}. {row['name_th']} — {row['price_baht']:,.2f} บาท" for index,row in enumerate(rows))
                +'\n\nตอบชื่อหรือเลขชนิดได้เลยครับ ไม่ต้องบอกจำนวนซ้ำ')


    def accept_extra_order(self, parsed):
        available={row['item_id'] for category in ('เครื่องดื่ม','ของหวาน') for row in self.extra_items(category)}
        for item in parsed['ambiguous']:
            item['candidates']=[key for key in item['candidates'] if key in available]
            if not item['candidates']:
                return 'ยังไม่มีไอศกรีมที่เลือกได้ตามข้อจำกัดของคุณครับ กรุณาตรวจส่วนผสมกับร้านก่อน'
            if len(item['candidates'])==1:
                parsed['orders'][item['candidates'][0]]=item['quantity']
        parsed['ambiguous']=[item for item in parsed['ambiguous'] if len(item['candidates'])>1]
        if parsed['ambiguous']:
            self.pending_extra_order=parsed
            return self.extra_choice_prompt()
        return self.set_checkout_extras(parsed['orders'])


    def resolve_extra_choice(self, message):
        from .database import records
        from .extra_order import normalize, parse_order
        pending=self.pending_extra_order
        text=normalize(message).strip()
        if any(word in text for word in ('แพ้','ไม่ชอบ','งบ','เปลี่ยนอาหาร','เปลี่ยนชุด')):
            self.pending_extra_order=None
            return None
        item=pending['ambiguous'][0]
        if text in {'ยกเลิก','ไม่เอาไอศกรีม','ยกเลิกไอศกรีม','ไม่รับไอศกรีม'}:
            pending['ambiguous'].pop(0)
        else:
            key=None
            if text.isdecimal() and 1<=int(text)<=len(item['candidates']):
                key=item['candidates'][int(text)-1]
            else:
                candidates=[row for row in records() if row['item_id'] in item['candidates']]
                suffix=re.search(r'\s*(?:x|×)?\s*(\d+)\s*(?:ชิ้น|ถ้วย|ลูก|รายการ|แก้ว)?$',text)
                choice_text=text[:suffix.start()].strip() if suffix else text
                matches=[row['item_id'] for row in candidates if choice_text and choice_text in normalize(row['name_th'])]
                if len(matches)==1:
                    key=matches[0]
                    if suffix:
                        item['quantity']=int(suffix.group(1))
                parsed=parse_order(message,records(),category=self.extra_category) if key is None else None
                if parsed and not parsed['ambiguous']:
                    chosen=set(parsed['orders']) & set(item['candidates'])
                    pending['orders'].update(parsed['orders'])
                    if chosen:
                        pending['ambiguous'].pop(0)
                        if pending['ambiguous']:
                            return self.extra_choice_prompt()
                        self.pending_extra_order=None
                        return self.set_checkout_extras(pending['orders'])
            if key is None:
                return self.extra_choice_prompt()
            pending['orders'][key]=item['quantity']
            pending['ambiguous'].pop(0)
        if pending['ambiguous']:
            return self.extra_choice_prompt()
        self.pending_extra_order=None
        return self.set_checkout_extras(pending['orders']) if pending['orders'] else self.checkout_summary()


    def checkout_action(self, action):
        """Ordered optional categories followed by a separate, revalidated final confirmation."""
        if self.order_closed:
            return CLOSING_MESSAGE
        if not self.food_choice:
            return 'กรุณาเลือกชุดอาหารก่อนครับ'
        if action in {'รับเครื่องดื่ม','เปลี่ยนเครื่องดื่ม'}:
            self.checkout_step='drinks_menu'
            return self.open_extras('เครื่องดื่ม')
        if action=='ไม่รับเครื่องดื่ม':
            from .database import records
            ids={row['item_id'] for row in records() if row['category']=='เครื่องดื่ม'}
            self.extras_plan={key:qty for key,qty in self.extras_plan.items() if key not in ids}
            self.sync_checkout_extras()
            return self.checkout_summary()
        if action in {'รับของหวาน','เปลี่ยนของหวาน'}:
            self.checkout_step='desserts_menu'
            return self.open_extras('ของหวาน')
        if action=='ไม่รับของหวาน':
            from .database import records
            ids={row['item_id'] for row in records() if row['category']=='ของหวาน'}
            self.extras_plan={key:qty for key,qty in self.extras_plan.items() if key not in ids}
            self.sync_checkout_extras()
            return self.checkout_summary()
        if action in {'ยืนยันรายการทั้งหมด','ยืนยัน','ตกลง','ถูกต้อง'} and self.food_choice is not None:
            if self.pending_extra_order:
                return self.extra_choice_prompt()
            result,error=self.compose_checkout()
            if error:
                self.checkout_result=None
                self.checkout_step='review_error'
                return error
            self.checkout_result=result
            self.state.last_result=result
            self.last_policy=result['policy_decision']
            self.order_closed=True
            self.checkout_step='closed'
            self.extra_category=None
            return '✅ ยืนยันรายการแล้วครับ ยังไม่ได้ส่งคำสั่งซื้อหรือชำระเงิน\n\n'+self.render_result(result)+'\n\n'+CLOSING_MESSAGE
        return 'เลือกเมนูหรือข้ามหมวดที่แสดงอยู่ได้เลยครับ'


    def compose_checkout(self):
        """Keep chosen food fixed. Extras may use the reserved portion of the full budget."""
        from .database import records, cents
        from .policy import validate_result
        from .tools import _resolve_quantity_items, _aggregate_by_item_id
        from .explain import explain
        if self.food_choice is None:
            return None,'กรุณาเลือกชุดอาหารก่อนครับ'
        menu=records()
        old=self.food_choice
        try:
            original=validate_result(old,menu,mode=self.data_mode)
            if not original['passed']:
                return None,'ราคา รายการ หรือข้อมูลส่วนผสมเปลี่ยนแล้ว กรุณารีเซ็ตคำถามเพื่อจัดชุดใหม่ครับ'
            constraints=copy.deepcopy(old['constraints'])
            args=self.build_arguments()
            # Food restrictions must remain exactly as they were when this food was selected.
            for key in ('budget','allergens','dislikes','preferred_keywords','hard_exclude_keywords',
                        'must_include_keywords','min_items','max_items','num_people'):
                if constraints.get(key)!=args.get(key):
                    return None,'ความต้องการอาหารเปลี่ยนแล้ว กรุณาเลือกชุดอาหารใหม่ก่อนครับ'
            for key in ('drink_selection','drink_quantity','drink_quantities','dessert_selection',
                        'dessert_quantity','include_dessert'):
                constraints[key]=args[key]
            constraints['drink_quantities']=constraints['drink_quantities'] or {}
            constraints['drinks_separate_from_budget']=False
            constraints['spend_ratio']=1.0
            catalog={row['item_id']:row for row in menu}
            if any(key not in catalog for key in self.extras_plan):
                return None,'เมนูเพิ่มเติมเปลี่ยนแล้ว กรุณาเรียกรายการใหม่ครับ'
            drinks=[copy.deepcopy(catalog[key]) for key,qty in self.extras_plan.items()
                    if catalog[key]['category']=='เครื่องดื่ม' for _ in range(qty)]
            desserts=[copy.deepcopy(catalog[key]) for key,qty in self.extras_plan.items()
                      if catalog[key]['category']=='ของหวาน' for _ in range(qty)]
            if len(drinks)>60 or len(desserts)>60:
                return None,'กรุณาระบุจำนวนเครื่องดื่มหรือของหวานรวมไม่เกินหมวดละ 60 ครับ'
            constraints['checkout_extras']=copy.deepcopy(self.extras_plan)
            if not self.state.max_items_explicit:
                constraints['checkout_food_limit']=60
                constraints['max_items']=180
            result=copy.deepcopy(old)
            food=[copy.deepcopy(row) for row in old['selected'] if row['category'] not in {'เครื่องดื่ม','ของหวาน'}]
            result['selected']=food+_aggregate_by_item_id(drinks+desserts)
            result['constraints']=constraints
            result['result_id']=str(uuid4())
            result['food_total_price']=sum(cents(row['subtotal_baht']) for row in food)/100
            result['total_price']=(sum(cents(row['subtotal_baht']) for row in food)
                                  +sum(cents(row['price_baht']) for row in drinks+desserts))/100
            result['max_items_requested']=constraints['max_items']
            result['item_count']=sum(row['quantity'] for row in result['selected'])
            result['distinct_dish_count']=len(result['selected'])
            result['drinks_separate_from_budget']=False
            result['spend_target']=result['budget']
            result['reserved_budget']=0
            result['budget_used_pct']=round(result['total_price']/result['budget']*100,1)
            result['drinks_cost']=sum(cents(row['price_baht']) for row in drinks)/100
            result['dessert_cost']=sum(cents(row['price_baht']) for row in desserts)/100
            result['dessert_included']=bool(self.state.wants_dessert)
            result['categories']=sorted({row['category'] for row in result['selected']})
            if cents(result['total_price'])>cents(result['budget']):
                excess=(cents(result['total_price'])-cents(result['budget']))/100
                return None,f'ยอดรวมเกินงบ {excess:,.2f} บาทครับ กรุณาลดจำนวนหรือเปลี่ยนเครื่องดื่ม/ของหวานก่อนยืนยัน'
            check=validate_result(result,menu,mode=self.data_mode)
            if not check['passed']:
                self.last_run['checkout_validation_issues']=check['issues']
                LOG.warning('checkout rejected: %s',check['issues'])
                if self.state.max_items_explicit and result['item_count']>constraints['max_items']:
                    return None,f"จำนวนรวม {result['item_count']} รายการ เกินจำนวน {constraints['max_items']} ที่คุณระบุครับ กรุณาลดรายการเพิ่มเติมก่อนยืนยัน"
                return None,'รายการเพิ่มเติมยังไม่ผ่านเงื่อนไข กรุณาตรวจจำนวนและรายการที่แพ้ครับ อาหารเดิมยังเก็บไว้'
            result['policy_decision']=check['policy_decision']
            result['explanation']=explain(result,menu)
            return result,None
        except (ValueError,TypeError,KeyError):
            return None,'รายการที่เลือกไม่พร้อมใช้งานครับ กรุณาเลือกเครื่องดื่ม/ของหวานใหม่'


    def checkout_summary(self):
        result,error=self.compose_checkout()
        self.checkout_result=result
        self.checkout_step='review_error' if error else 'review'
        if error:
            return error
        return '**สรุปรายการทั้งหมดก่อนยืนยัน**\n\n'+self.render_result(result)+'\n\nกด «ยืนยันรายการทั้งหมด» เพื่อจบรายการ หรือพิมพ์ เครื่องดื่ม / ของหวาน เพื่อดูเมนูเพิ่มเติมได้ครับ'


    def select_option(self, index):
        """Confirm a simulated selection, rechecking current catalog and session constraints."""
        if self.order_closed:
            return CLOSING_MESSAGE
        from .database import records
        from .policy import validate_result
        if not 0 <= index < len(self.last_options):
            return 'กรุณาเลือกชุดที่แสดงอยู่ หรือให้จัดชุดใหม่ครับ'
        selected=self.last_options[index]
        expected=self.build_arguments()
        constraints={k:v for k,v in selected['constraints'].items() if k!='excluded_item_ids'}
        expected['drink_quantities']=expected['drink_quantities'] or {}
        if constraints != expected:
            self.clear_choices()
            return 'ความต้องการเปลี่ยนแล้ว ขอจัดชุดใหม่ก่อนยืนยันครับ'
        try:
            checked=validate_result(selected, records(), mode=self.data_mode)
        except (ValueError, TypeError, KeyError):
            checked={'passed':False}
        if not checked['passed']:
            self.clear_choices()
            return 'รายการหรือราคาเปลี่ยนแล้ว ขอจัดชุดใหม่ก่อนยืนยันครับ'
        self.state.last_result=selected
        self.last_policy=checked['policy_decision']
        self.confirmed_option=index
        if self.consumer_flow:
            self.food_choice=copy.deepcopy(selected)
            self.checkout_result=None
            self.extras_plan={row['item_id']:row['quantity'] for row in selected['selected'] if row['category'] in {'เครื่องดื่ม','ของหวาน'}}
            self.extra_category=None
            self.pending_confirmation=False
            return self.checkout_summary()
        return (f'เลือกชุดที่ {index+1} แล้วครับ ✅ นี่เป็นสรุปชุดสำหรับนำไปแจ้งร้าน ยังไม่ได้ส่งคำสั่งซื้อ\n\n'
                +self.render_result(selected)
                +'\n\n'+(CLOSING_MESSAGE if self.consumer_flow else 'อยากเปลี่ยนเมนูหรือปรับจำนวน บอกต่อได้เลยครับ ผมจะใช้ข้อมูลเดิมให้'))
