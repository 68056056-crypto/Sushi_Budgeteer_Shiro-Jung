"""Confirmed meal details, extraction and consumer-facing constraint explanations.

Mixin methods operate on the owning Agent session; no separate conversation store.
"""
from __future__ import annotations
import asyncio
import json
import logging
import re
from dataclasses import asdict
from pydantic import BaseModel, Field, ConfigDict
from langchain_core.messages import SystemMessage
from .extraction import EXTRACT_PROMPT, _sanitize_extraction, contextual_answer
from .presentation import ALLERGY_WARNING
from .optimization_config import INITIAL_SPEND_RATIO, MIN_INTAKE_BUDGET_PER_PERSON
from .dietary import exclusion_label
from .meat_scope import MEAT_CHOICES, MEAT_WORDS, defer_meat_guess
from .telemetry import model_error
LOG=logging.getLogger('shiro_jung.agent')

class Extraction(BaseModel):
    model_config=ConfigDict(extra='ignore',allow_inf_nan=False)
    budget: float | None=Field(None,gt=0,le=100000)
    budget_delta: float | None=Field(None,ge=-100000,le=100000)
    budget_change_unclear: bool=False
    allergens: list[str]=Field(default_factory=list,max_length=30)
    dislikes: list[str]=Field(default_factory=list,max_length=30)
    preferred_keywords: list[str]=Field(default_factory=list,max_length=30)
    hard_exclude_keywords: list[str]=Field(default_factory=list,max_length=30)
    must_include_keywords: list[str]=Field(default_factory=list,max_length=30)
    min_items: int | None=Field(None,ge=1,le=60)
    max_items: int | None=Field(None,ge=1,le=60)
    num_people: int | None=Field(None,ge=1,le=60)
    allergy_check_answered: bool=False
    wants_dessert: bool | None=None
    drink_selection: list[str]=Field(default_factory=list,max_length=10)
    dessert_selection: list[str]=Field(default_factory=list,max_length=10)
    drink_quantity: int | None=Field(None,ge=1,le=60)
    drink_quantities: dict[str,int]=Field(default_factory=dict)
    dessert_quantity: int | None=Field(None,ge=1,le=60)
    drinks_budget_mode: str | None=None
    intent: str='info'


class IntakeMixin:
    def _extract_intent(self, message):
        if getattr(self,"_picker_update",None) is not None:
            return Extraction.model_validate(_sanitize_extraction(self._picker_update,self.state.last_asked_field,message)).model_dump()
        direct=contextual_answer(self.state.last_asked_field,message)
        if direct is not None:
            return Extraction.model_validate(_sanitize_extraction(direct,self.state.last_asked_field,message)).model_dump()
        state=asdict(self.state)
        state.pop('conversation'); state.pop('last_result')
        prompt=(EXTRACT_PROMPT+'\nคืน JSON object เท่านั้น อย่าลบ allergen ที่ไม่รู้จัก ให้คงชื่อเดิมไว้'
                +'\nบริบทปัจจุบัน:'+json.dumps(state,ensure_ascii=False)
                +f'\n[บริบท: คำถามล่าสุดที่ระบบถามคือเรื่อง {self.state.last_asked_field!r}]'
                +'\nข้อความผู้ใช้:'+message)
        response=self.llm.invoke([SystemMessage(content=prompt)])
        self._record_usage(response, 'extraction')
        text=re.sub(r'^```(?:json)?\s*|\s*```$','',response.content.strip())
        raw=json.loads(text)
        if not isinstance(raw,dict): raise ValueError('expected object')
        raw=_sanitize_extraction(raw,self.state.last_asked_field,message)
        if self.consumer_flow and not re.search(
                r'\d+\s*(?:รายการ|จาน)|(?:รายการ|จาน|จำนวนอาหาร).{0,12}\d+|(?:max|min|items|plates)\s*\d+',message,re.IGNORECASE):
            # Never turn an echoed default from model context into a user-imposed hard cap.
            raw={**raw,'max_items':None,'min_items':None}
        if (self.consumer_flow and self.state.wants_dessert is False
                and not re.search(r'ของหวาน|ขอหวาน|dessert|โมจิ|ไอศกรีม|ขนม',message,re.IGNORECASE)):
            raw={**raw,'wants_dessert':None,'dessert_selection':[],'dessert_quantity':None}
        raw=defer_meat_guess(raw,message)
        return Extraction.model_validate(raw).model_dump()


    def intake_budget_warning(self):
        """Stop consumer planning early while preserving all stated meal details."""
        s=self.state
        if not self.consumer_flow or s.budget is None or s.num_people is None:
            return None
        from .database import cents
        minimum=cents(MIN_INTAKE_BUDGET_PER_PERSON)*s.num_people
        if cents(s.budget)>=minimum:
            return None
        self.pending_confirmation=False
        self.details_confirmed=False
        self.clear_choices()
        s.last_asked_field='budget'
        self.last_run['intake_check']={'status':'needs_budget_revision',
            'code':'budget_per_person_below_minimum','budget':s.budget,'num_people':s.num_people,
            'budget_per_person':round(s.budget/s.num_people,2),
            'minimum_budget':minimum/100,'minimum_per_person':MIN_INTAKE_BUDGET_PER_PERSON}
        return (f'งบ {s.budget:,.2f} บาทสำหรับ {s.num_people} คน เฉลี่ยคนละ {s.budget/s.num_people:,.2f} บาท '
                'อาจน้อยเกินไปสำหรับจัดอาหารให้ทุกคนครับ '
                f'แนะนำงบเริ่มต้นอย่างน้อย {minimum/100:,.2f} บาท หรือปรับจำนวนคนได้เลย '
                'พิมพ์งบใหม่หรือจำนวนคนที่ต้องการได้ครับ ผมจำการแพ้และความชอบเดิมไว้ให้')


    def missing_fields(self):
        s=self.state
        if self.consumer_flow:
            return [key for key,missing in [('budget',s.budget is None),
                    ('num_people',s.num_people is None),('allergy',not s.allergy_check_done)] if missing]
        checks=[('budget',s.budget is None),('num_people',s.num_people is None),
                ('allergy',not s.allergy_check_done),('drinks',not s.drink_selection),
                ('drink_quantity',s.drink_quantity is None),
                ('drinks_budget_mode',s.drinks_budget_mode is None),
                ('dessert',s.wants_dessert is None),
                ('dessert_selection',s.wants_dessert is True and not s.dessert_selection),
                ('dessert_quantity',s.wants_dessert is True and s.dessert_quantity is None)]
        return [key for key,missing in checks if missing]


    def order_summary(self):
        s=self.state
        allergy=[a for a in s.allergens if a not in self.pending_allergy_removals]
        names=', '.join(self._ALLERGEN_TH.get(a,a) for a in allergy)
        lines=['**ขอเช็กมื้อของคุณครั้งเดียวครับ 🍱**',
               f'- งบ {s.budget:,.2f} บาท · {s.num_people} คน',
               '- แพ้อาหาร: '+(names or 'ไม่มีที่แจ้ง — กดยืนยันด้านล่างหากไม่แพ้'),
               '- ไม่กิน: '+(', '.join(exclusion_label(word) for word in s.hard_exclude_keywords) or 'ไม่ได้ระบุ'),
               '- ชอบ: '+(', '.join(s.preferred_keywords) or 'ไม่ได้ระบุ'),
               '- ไม่ชอบ: '+(', '.join(s.dislikes) or 'ไม่ได้ระบุ')]
        if s.drink_selection:
            drinks=(', '.join(f'{name} {qty} แก้ว' for name,qty in s.drink_quantities.items())
                    if s.drink_quantities else ', '.join(s.drink_selection)+f' รวม {s.drink_quantity or s.num_people} แก้ว')
            lines.append('- เครื่องดื่ม: '+drinks)
        else:
            lines.append('- เครื่องดื่ม: ไม่เพิ่มในชุด')
        if s.wants_dessert:
            lines.append('- ของหวาน: '+(', '.join(s.dessert_selection) or 'กรุณาบอกชื่อที่ต้องการ')
                         +f' {s.dessert_quantity or s.num_people} ชิ้น')
        else:
            lines.append('- ของหวาน: ไม่รับ')
        lines.append('- จำนวนรายการ: '+(f'ไม่เกิน {s.max_items} รายการ' if s.max_items_explicit else 'ปรับให้ใกล้งบ ไม่เกิน 60 รายการ'))
        lines.append('- ค่าเครื่องดื่ม/ของหวาน: '+('คิดเพิ่มนอกงบ' if s.drinks_budget_mode=='separate' else 'รวมในงบ'))
        if self.pending_allergy_removals:
            corrected=', '.join(self._ALLERGEN_TH.get(a,a) for a in self.pending_allergy_removals)
            lines.append('คุณขอแก้ว่าไม่ได้แพ้ '+corrected+' — จะเปลี่ยนข้อมูลเมื่อคุณกดยืนยันเท่านั้น')
        return '\n\n'.join([lines[0], '\n'.join(lines[1:]),
            'ถ้าตรงแล้วกดยืนยันเพื่อจัดชุด หรือพิมพ์แก้เฉพาะส่วนที่ต้องการได้เลยครับ'])


    def _confirm_order(self):
        if self.pending_meat_scope:
            return self.meat_scope_prompt()
        s=self.state
        if s.budget is None or s.num_people is None:
            return 'ขอทราบงบและจำนวนคนก่อนจัดชุดครับ'
        warning=self.intake_budget_warning()
        if warning:
            return warning
        s.allergens=[a for a in s.allergens if a not in self.pending_allergy_removals]
        self.pending_allergy_removals=[]
        s.allergy_check_done=True
        if s.wants_dessert is None:
            s.wants_dessert=False
        if s.drink_selection and s.drink_quantity is None:
            s.drink_quantity=sum(s.drink_quantities.values()) if s.drink_quantities else s.num_people
        if s.wants_dessert and s.dessert_quantity is None:
            s.dessert_quantity=s.num_people
        if s.drinks_budget_mode is None:
            s.drinks_budget_mode='within'
        self.pending_confirmation=False
        self.details_confirmed=True
        s.last_asked_field=None
        self.clear_choices()
        self._replan=True
        try:
            return asyncio.run(self._run('จัดชุดตามข้อมูลที่ยืนยัน'))
        except Exception as exc:
            self.last_run.setdefault('model_errors',[]).append(model_error(exc,'planning'))
            LOG.exception('confirmed order failed')
            self.clear_choices()
            return 'จัดชุดไม่สำเร็จชั่วคราวครับ ลองใหม่ได้เลย ข้อมูลเดิมยังอยู่'


    def item_limit(self):
        # The old implicit 20-item cap prevents a 3000-baht meal from fitting its budget.
        # Explicit user limits always win; retain the backend's existing 60-item bound.
        if self.consumer_flow and not self.state.max_items_explicit:
            return 60
        return self.state.max_items


    def build_arguments(self):
        s=self.state
        return dict(budget=s.budget,allergens=s.allergens,dislikes=s.dislikes,
          preferred_keywords=s.preferred_keywords,hard_exclude_keywords=s.hard_exclude_keywords,
          must_include_keywords=s.must_include_keywords,min_items=s.min_items,max_items=self.item_limit(),
          num_people=s.num_people,drink_selection=s.drink_selection,drink_quantity=s.drink_quantity,
          drink_quantities=s.drink_quantities or None,
          drinks_separate_from_budget=s.drinks_budget_mode=='separate',include_dessert=s.wants_dessert,
          dessert_selection=s.dessert_selection,dessert_quantity=s.dessert_quantity,
          spend_ratio=INITIAL_SPEND_RATIO if self.consumer_flow else 1.0)


    @staticmethod
    def _unknown_drinks(extracted):
        """Names the user asked for that the drink catalog cannot match (e.g. water not on the menu)."""
        names=list(dict.fromkeys([*(extracted.get('drink_selection') or []),*(extracted.get('drink_quantities') or {})]))
        if not names: return [],[]
        from .database import records
        from .tools import _resolve_quantity_items
        menu=records()
        available=[r['name_th'] for r in menu if r.get('category')=='เครื่องดื่ม']
        unknown=[]
        for name in names:
            try: _resolve_quantity_items(menu,'เครื่องดื่ม',[str(name)],1)
            except ValueError: unknown.append(str(name))
        return unknown,available


    _ALLERGEN_TH={'beef':'เนื้อวัว','chicken':'ไก่','echinoderm':'หอยเม่น/อูนิ','fish':'ปลา','crustacean':'สัตว์น้ำมีเปลือก (กุ้ง/ปู)','molluscs':'หอย/ปลาหมึก','egg':'ไข่',
                  'milk':'นม','peanut':'ถั่วลิสง','tree_nuts':'ถั่วเปลือกแข็ง','sulphites':'ซัลไฟต์','gluten':'กลูเตน/แป้งสาลี','soy':'ถั่วเหลือง','sesame':'งา','pork':'หมู'}


    def _friendly_issues(self, issues):
        issues=[str(i) for i in (issues or [])]
        if self.data_mode=='strict' and self.state.allergens and any(
                'allergen' in i or 'ไม่มีอาหารหลัก' in i or 'unknown_evidence' in i for i in issues):
            from .state import KNOWN_ALLERGENS
            self.allergy_simulation_available=(self.consumer_flow and self.details_confirmed
                and set(self.state.allergens)<=KNOWN_ALLERGENS)
            message='ข้อมูลส่วนผสมยังไม่ยืนยันกับร้าน จึงยังจัดชุดสำหรับการสั่งจริงไม่ได้ครับ'
            if self.allergy_simulation_available:
                message+=' หากต้องการวางแผน สามารถกด «ดูชุดจำลองจากข้อมูลเมนู» ระบบจะตัดเมนูที่มีแท็กสารที่คุณแพ้ออก โดยยังต้องให้ร้านตรวจส่วนผสมก่อนรับประทาน ไม่ใช้ชุดจำลองตัดสินใจกรณีแพ้รุนแรง'
            else:
                message+=' กรุณาให้พนักงานร้านช่วยเลือกเมนูและตรวจส่วนผสมก่อนครับ'
            return message+'\n\n'+ALLERGY_WARNING
        if any('opa_unavailable' in i for i in issues):
            return 'ระบบตรวจรายการไม่พร้อมชั่วคราว กรุณาลองใหม่ครับ'
        if any('เครื่องดื่ม' in i or 'ของหวาน' in i for i in issues):
            message='เครื่องดื่มหรือของหวานที่เลือกอาจขัดกับข้อจำกัด กรุณาเลือกใหม่ครับ'
        elif any('งบ' in i for i in issues):
            message='ยังจัดชุดในงบนี้ไม่ได้ครับ ลองเพิ่มงบหรือลดจำนวนรายการได้เลย'
        else:
            message='ยังจัดชุดตามเงื่อนไขนี้ไม่ได้ครับ ลองเปลี่ยนเมนูหรือจำนวน โดยผมจะเก็บข้อจำกัดการแพ้เดิมไว้'
        return message+('\n\n'+ALLERGY_WARNING if self.state.allergens else '')

    def meat_scope_prompt(self):
        label={'dislikes':'ไม่ชอบ','allergens':'แพ้','hard_exclude_keywords':'ไม่กิน'}[self.pending_meat_scope]
        return f'คุณ{label}เนื้อสัตว์บกชนิดไหนครับ? เลือก หมู / เนื้อวัว / ไก่ / สัตว์บกทั้งหมด ได้เลย ปลาและอาหารทะเลยังเลือกได้ตามข้อจำกัดเดิม ผมจำข้อมูลมื้อเดิมไว้ครับ'

    def resolve_meat_choice(self, message):
        choice=message.strip()
        if choice not in MEAT_CHOICES:
            return None
        kind=self.pending_meat_scope
        tags=MEAT_CHOICES[choice]
        values=tags if kind=='allergens' else [MEAT_WORDS[tag] for tag in tags]
        self.state.update_from_extraction({kind:values})
        self.pending_meat_scope=None
        self.state.last_asked_field=None
        self.details_confirmed=False
        self.clear_choices()
        if self.state.budget is None or self.state.num_people is None:
            missing=[label for label,value in [('งบรวม',self.state.budget),('จำนวนคน',self.state.num_people)] if value is None]
            return 'รับทราบครับ ขอทราบ'+'และ'.join(missing)+'เพื่อสรุปมื้อให้ครับ'
        warning=self.intake_budget_warning()
        if warning:
            return warning
        self.pending_confirmation=True
        return self.order_summary()
