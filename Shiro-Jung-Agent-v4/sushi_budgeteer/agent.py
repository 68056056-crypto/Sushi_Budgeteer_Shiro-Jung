"""Per-session Agent lifecycle and consumer message routing.

Intake, MCP planning and checkout responsibilities are implemented in focused mixins.
"""
from __future__ import annotations
import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Iterator
from uuid import uuid4
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from .state import BudgeteerState
from .credentials import clean_api_key, InvalidAPIKeyFormat
from .extraction import _sanitize_extraction, requested_allergy_corrections
from .database import cents
from .meat_scope import MEAT_CHOICES, meat_relation
from .presentation import render_menu, ALLERGY_WARNING, CLOSING_MESSAGE
from .telemetry import redact, model_error
from .intake import IntakeMixin, Extraction
from .planning import PlanningMixin, SYSTEM_PROMPT
from .checkout import CheckoutMixin
LOG=logging.getLogger('shiro_jung.agent')

def _root_cause(exc):
    """Unwrap anyio/asyncio ExceptionGroups so the user sees the real error type."""
    while hasattr(exc,'exceptions') and getattr(exc,'exceptions'):
        exc=exc.exceptions[0]
    return exc


GREETING_MESSAGE='สวัสดีครับ ผม Shiro-Jung ช่วยจัดมื้อซูชิให้พอดีงบ กรุณาบอกงบและจำนวนคนครับ'


class BudgeteerAgent(IntakeMixin, PlanningMixin, CheckoutMixin):
    def __init__(self, api_key=None, model=None, llm=None, consumer_flow=False):
        load_dotenv()
        self._api_key=clean_api_key(api_key or os.getenv('OPENAI_API_KEY') or os.getenv('SUSHI_OPENAI_API_KEY'))
        if llm is None and self._api_key is None:
            raise InvalidAPIKeyFormat('Configure a non-empty API key secret before calling the provider.')
        self.llm=llm if llm is not None else ChatOpenAI(
            api_key=self._api_key,
            model=model or os.getenv('OPENAI_MODEL','gpt-4o-mini'),temperature=0,
            timeout=30,max_retries=1)
        self.consumer_flow=consumer_flow
        self.extra_category=None
        self.order_closed=False
        self.checkout_step=None
        self.food_choice=None
        self.checkout_result=None
        self.extras_plan={}
        self.pending_extra_order=None
        self.pending_confirmation=False
        self.details_confirmed=False
        self.pending_allergy_removals=[]
        self.pending_meat_scope=None
        self._turn_llm=None
        self.model_source='scripted' if llm is not None else 'live'
        self.model_name=model or os.getenv('OPENAI_MODEL','gpt-4o-mini')
        self.last_policy=None
        self.last_options=[]
        self.confirmed_option=None
        self._replan=False
        self._has_recommended=False
        self.last_run={}
        self.state=BudgeteerState()
        self.session_id=str(uuid4())
        self.last_trace=[]
        self.data_mode=os.getenv('SUSHI_DATA_MODE','strict')
        self.configured_data_mode=self.data_mode
        self.allergy_simulation_consent=False
        self.allergy_simulation_available=False


    def _record_usage(self,response,phase):
        self.last_run['model_calls']=self.last_run.get('model_calls',0)+1
        phases=self.last_run.setdefault('model_calls_by_phase',{})
        phases[phase]=phases.get(phase,0)+1
        usage=getattr(response,'usage_metadata',None)
        self.last_run.setdefault('usage',{'input_tokens':0,'output_tokens':0,'total_tokens':0})
        if usage:
            self.last_run['usage_responses']=self.last_run.get('usage_responses',0)+1
            for key in self.last_run['usage']:
                self.last_run['usage'][key]+=usage.get(key,0)
        self.last_run.setdefault('model_events',[]).append({'phase':phase,
            'tools_selected':[x['name'] for x in getattr(response,'tool_calls',[])],
            'usage_reported':bool(usage)})


    def run_report(self):
        return redact({**self.last_run,'trace':self.last_trace,'policy_decision':self.last_policy})


    def reset_order(self):
        self.data_mode=self.configured_data_mode
        self.allergy_simulation_consent=False
        self.allergy_simulation_available=False
        self.state.reset()
        self.clear_choices()
        self.extra_category=None
        self.order_closed=False
        self.checkout_step=None
        self.food_choice=None
        self.checkout_result=None
        self.extras_plan={}
        self.pending_extra_order=None
        self.pending_confirmation=False
        self.details_confirmed=False
        self.pending_allergy_removals=[]
        self.pending_meat_scope=None
        self._has_recommended=False
        self.last_trace=[]
        self.last_run={}


    @staticmethod
    def render_result(result):
        return render_menu(result)


    def clear_choices(self):
        self.allergy_simulation_available=False
        self.last_options=[]
        self.confirmed_option=None
        self.state.last_result=None
        self.last_policy=None


    def _chat(self,user_message):
        if self.order_closed:
            return CLOSING_MESSAGE
        text=re.sub(r'\s*(?:ครับ|ค่ะ|คะ)[!? ]*$','',user_message.strip())
        from .database import records
        from .extra_order import unavailable_order_names
        unknown=unavailable_order_names(text,records(),category=self.extra_category,allow_name_only=self.food_choice is not None or self.extra_category is not None)
        if unknown:
            return 'ไม่มี '+', '.join(unknown)+' ในเมนูครับ กรุณาเลือกชื่อจากเมนู รายการอาหารเดิมยังอยู่ครับ'
        if self.state.last_asked_field=='required_menu':
            from .menu_matching import exact_match
            chosen=[row for row in records() if exact_match(row,text)]
            unresolved=[term for term in self.state.required_keywords if not any(exact_match(row,term) for row in records())]
            if len(chosen)==1 and unresolved:
                self.state.required_keywords=[chosen[0]['name_th'] if term==unresolved[0] else term for term in self.state.required_keywords]
                self.state.last_asked_field=None
                self.pending_confirmation=True
                if self.state.budget is None or self.state.num_people is None:
                    self.pending_confirmation=False
                    return 'รับทราบเมนูที่เลือกครับ กรุณาบอกงบรวมและจำนวนคน ผมจำการแพ้และข้อห้ามเดิมไว้'
                return self.required_menu_warning() or self.order_summary()
        if re.search(r'ราคา|กี่บาท|เท่าไหร่',text) and not re.search(r'งบ|เพิ่มงบ|ลดงบ',text):
            from .database import records
            from .optimizer import matches_any_keyword
            query=re.sub(r'ราคา|กี่บาท|เท่าไหร่|เท่าไร|ขอทราบ|ถาม|เมนู|ครับ|ค่ะ|ไหม|\s','',text)
            found=[row for row in records() if query and matches_any_keyword(row,[query])]
            if found:
                return '\n'.join(f"- {row['name_th']} — {float(row['price_baht']):,.2f} บาท" for row in found)+'\n\nรายการอาหารและชุดที่เลือกได้ยังอยู่ครับ'
            return 'ยังไม่พบเมนูที่ถามราคาครับ กรุณาระบุชื่อเมนู เช่น โอโทโร่ ราคาเท่าไหร่ รายการและตัวเลือกเดิมยังอยู่ครับ'
        if self.pending_meat_scope and text in MEAT_CHOICES:
            self.state.add_message('user',user_message)
            answer=self.resolve_meat_choice(text)
            self.state.add_message('assistant',answer)
            return answer
        if text=='ดูชุดจำลองจากข้อมูลเมนู':
            from .state import KNOWN_ALLERGENS
            if (not self.allergy_simulation_available or not self.details_confirmed
                    or not self.state.allergens or not set(self.state.allergens)<=KNOWN_ALLERGENS):
                return 'กรุณายืนยันงบและข้อมูลการแพ้ก่อนครับ'
            self.allergy_simulation_consent=True
            self.allergy_simulation_available=False
            self.data_mode='simulation'
            self.last_run['allergy_simulation_consent']=True
            self.last_trace=[]
            return self._confirm_order()
        desserts={'ของหวาน','ขนม','เมนูของหวาน','ขอดูเมนูของหวาน','รับของหวาน','เอาของหวาน','เพิ่มของหวาน','เมนูขนม','ขนมมีอะไรบ้าง'}
        drinks={'เครื่องดื่ม','น้ำ','เมนูน้ำ','เมนูเครื่องดื่ม','ขอดูเมนูน้ำ','ขอดูเมนูเครื่องดื่ม','รับน้ำ','รับเครื่องดื่ม','เพิ่มน้ำ','น้ำมีอะไรบ้าง','เครื่องดื่มมีอะไรบ้าง'}
        if self.consumer_flow and text in desserts|drinks:
            answer=self.open_extras('ของหวาน' if text in desserts else 'เครื่องดื่ม')
            self.state.add_message('user',user_message)
            self.state.add_message('assistant',answer)
            return answer
        if self.checkout_step:
            if self.pending_extra_order:
                answer=self.resolve_extra_choice(text)
                if answer is not None:
                    return answer
            if text in {'ไม่รับเครื่องดื่ม','ไม่รับน้ำ','ไม่รับของหวาน','เปลี่ยนเครื่องดื่ม','เปลี่ยนของหวาน','ยืนยันรายการทั้งหมด','ยืนยัน','ตกลง','ถูกต้อง'}:
                return self.checkout_action({'ไม่รับน้ำ':'ไม่รับเครื่องดื่ม'}.get(text,text))
            from .database import records
            from .extra_order import parse_order
            parsed=parse_order(text,records(),category=self.extra_category)
            if parsed:
                return self.accept_extra_order(parsed)
            from .extra_order import order_aliases,normalize
            aliases=order_aliases(records(),self.extra_category)
            ids=aliases.get(normalize(text),[])
            if len(ids)==1:
                row=next(row for row in records() if row['item_id']==ids[0])
                return f"{row['name_th']} ราคา {row['price_baht']:,.2f} บาทครับ รับกี่แก้ว/ชิ้น? พิมพ์ เช่น {row['name_th']} 1"
            if text in {'สรุป','สรุปรายการ','ยอดรวม'}:
                return self.checkout_summary()
            if text.startswith(('ยกเลิก','ไม่เอา','ลบ')):
                from .database import records
                name=re.sub(r'^(?:ยกเลิก|ไม่เอา|ลบ)\s*','',text)
                from .optimizer import matches_any_keyword
                ids={row['item_id'] for row in records() if row['item_id'] in self.extras_plan and matches_any_keyword(row,[name])}
                if ids:
                    self.extras_plan={key:qty for key,qty in self.extras_plan.items() if key not in ids}
                    self.sync_checkout_extras()
                    return self.checkout_summary()
            if not any(word in text for word in ('งบ','แพ้','ไม่ชอบ','ชอบ','ไม่กิน','ไม่ทาน','งด','เปลี่ยนอาหาร','เปลี่ยนชุด','จัดใหม่')):
                return 'พิมพ์ชื่อเมนูและจำนวน เช่น น้ำส้ม 1 แก้ว หรือ ยกเลิกน้ำส้ม ได้เลยครับ อาหารที่เลือกไว้ยังอยู่ หากครบแล้วพิมพ์ ยืนยันรายการทั้งหมด'

        if self.consumer_flow and self.pending_confirmation:
            if user_message.strip() in {'ยืนยัน','ยืนยันข้อมูล','ใช่','ใช่ครับ','ถูกต้อง','ถูกต้องครับ','ตกลง','โอเค','ได้เลย','ยืนยันข้อมูลและจัดชุด','ยืนยันว่าไม่แพ้และจัดชุด'}:
                answer=self._confirm_order()
                self.state.add_message('user',user_message)
                self.state.add_message('assistant',answer)
                return answer
            if user_message.strip() in {'แก้ไขข้อมูล','ไม่','ไม่ใช่','ยังไม่ใช่'}:
                self.pending_confirmation=False
                self.state.last_asked_field='order_details'
                return 'พิมพ์เฉพาะส่วนที่อยากแก้ได้เลยครับ เช่น ไม่ชอบปลาหมึก ไม่ได้แพ้ หรือ ไม่รับของหวาน'
        choice=re.fullmatch(r'(?:เลือก\s*)?(?:ชุด(?:ที่)?\s*)?([12])',user_message.strip())
        if self.last_options and choice:
            answer=self.select_option(int(choice.group(1))-1)
            self.state.add_message('user',user_message)
            self.state.add_message('assistant',answer)
            return answer
        self.extra_category=None
        self.checkout_step=None
        self.food_choice=None
        self.checkout_result=None
        had_result=self._has_recommended or bool(self.last_options or self.state.last_result)
        self.last_trace=[]
        self.clear_choices()
        self._replan=False
        if len(user_message)>4000: return 'กรุณาย่อข้อความให้ไม่เกิน 4000 ตัวอักษรครับ'
        try:
            extracted=self._extract_intent(user_message)
            budget=extracted.get('budget')
            delta=extracted.get('budget_delta')
            invalid_budget=(budget is not None and budget<=0) or (delta is not None and self.state.budget is not None and self.state.budget+delta<=0)
            if invalid_budget:
                valid={**extracted,'budget':None,'budget_delta':None}
                if valid.get('min_items') and valid.get('max_items') and valid['min_items']>valid['max_items']:
                    valid.update(min_items=None,max_items=None)
                self.state.update_from_extraction(valid)
                if budget is not None and budget<=0:
                    self.state.budget=None
                self.pending_confirmation=False
                self.state.last_asked_field='budget'
                self.last_run['intake_check']={'status':'needs_budget_revision','code':'budget_must_be_positive','extracted_budget':budget}
                return 'งบต้องมากกว่า 0 บาทครับ กรุณาระบุงบใหม่ ผมยังเก็บจำนวนคน การแพ้และความชอบไว้ให้'

            cancelled=[kw for kw in self.state.required_keywords
                       if re.search(r'(?:ยกเลิก|ไม่เอา|ไม่ต้องมี)\s*'+re.escape(kw),user_message)]
            if cancelled:
                self.state.required_keywords=[kw for kw in self.state.required_keywords if kw not in cancelled]
                self.state.preferred_keywords=[kw for kw in self.state.preferred_keywords if kw not in cancelled]
                for key in ('required_keywords','preferred_keywords'):
                    extracted[key]=[kw for kw in extracted.get(key,[]) if kw not in cancelled]


            if extracted.get('drinks_budget_mode') not in {None,'within','separate'}:
                return 'กรุณาระบุว่าจะรวมค่าเครื่องดื่ม/ของหวานในงบหรือคิดแยกครับ'
            if extracted.get('budget_delta') is not None and self.state.budget is not None and self.state.budget+extracted['budget_delta']<=0:
                return 'งบหลังปรับต้องมากกว่า 0 บาท กรุณาระบุใหม่ครับ'
            effective_min=extracted.get('min_items') or self.state.min_items
            effective_max=extracted.get('max_items') or self.item_limit()
            if effective_min>effective_max:
                valid={**extracted,'min_items':None,'max_items':None}
                self.state.update_from_extraction(valid)
                self.pending_confirmation=False
                self.state.last_asked_field='item_bounds'
                return 'จำนวนขั้นต่ำมากกว่าจำนวนสูงสุดครับ ผมเก็บงบ จำนวนคน การแพ้และความชอบไว้แล้ว กรุณาระบุเฉพาะจำนวนจานใหม่ เช่น อย่างน้อย 5 จาน ไม่เกิน 10 จาน'
            if extracted.get('budget') is not None: cents(extracted['budget'])
            if extracted.get('budget_delta') is not None:
                cents(abs(extracted['budget_delta']))
                new_budget=(self.state.budget or 0)+extracted['budget_delta']
                if not 0<new_budget<=100000:
                    return 'กรุณาระบุงบใหม่ระหว่าง 0.01–100000 บาทครับ'
            unknown,available=self._unknown_extras(extracted)
            if unknown:
                # Keep the rest of this answer (budget, people...) but drop the drink plan,
                # because a split that includes an off-menu drink cannot be priced.
                extracted={**extracted,'drink_selection':[],'drink_quantities':{},'drink_quantity':None,'dessert_selection':[],'dessert_quantity':None,'wants_dessert':None}
            corrections=requested_allergy_corrections(user_message,self.state.allergens)
            self.pending_allergy_removals=list(dict.fromkeys([*self.pending_allergy_removals,*corrections]))
            self.pending_allergy_removals=[a for a in self.pending_allergy_removals if a not in extracted.get('allergens',[])]
            self.state.update_from_extraction(extracted)
            kind=meat_relation(user_message)
            if kind:
                self.pending_meat_scope=kind
                self.pending_confirmation=False
                self.details_confirmed=False
            request_warning=self.required_menu_warning()
            if request_warning:
                return request_warning
            if self.pending_meat_scope:
                self.state.last_asked_field='meat_scope'
                answer=self.meat_scope_prompt()
                self.state.add_message('user',user_message)
                self.state.add_message('assistant',answer)
                return answer
            if self.state.last_asked_field not in self.missing_fields():
                self.state.last_asked_field=None
            # Preference updates after a recommendation mean replan, not an empty search.
            explicit_search=any(word in user_message for word in ('มีเมนู','ราคาเท่า','ค้นหา','ดูเมนู'))
            self._replan=had_result and not explicit_search and (
                extracted.get('intent')=='optimize' or any(extracted.get(k) for k in (
                    'preferred_keywords','dislikes','allergens','hard_exclude_keywords',
                    'must_include_keywords','budget','budget_delta','num_people'))
                or any(word in user_message for word in ('จัดใหม่','ชุดใหม่','เปลี่ยนเมนู','อีกชุด','อยากกิน','อยากทาน')))
            if unknown:
                self.pending_confirmation=False
                self.state.last_asked_field='drinks'
                answer=(f"ไม่มี {', '.join(unknown)} ในเมนูครับ "
                        f"เลือกได้จาก: {', '.join(available)} — กรุณาระบุเครื่องดื่มและจำนวนแต่ละอย่างใหม่ครับ")
                self.state.add_message('user',user_message);self.state.add_message('assistant',answer)
                return answer
        except Exception as exc:
            cause=_root_cause(exc)
            self.last_run.setdefault('model_errors',[]).append(model_error(cause,'extraction'))
            LOG.exception('intent extraction failed: %s',type(cause).__name__)
            return 'อ่านความต้องการไม่สำเร็จชั่วคราว ลองส่งข้อความอีกครั้งได้เลยครับ ผมยังเก็บข้อมูลเดิมไว้'
        self.state.add_message('user',user_message)
        if self.consumer_flow and not explicit_search:
            missing=[]
            if self.state.budget is None: missing.append('งบรวมกี่บาท')
            if self.state.num_people is None: missing.append('ทานกี่คน')
            if missing:
                self.pending_confirmation=False
                self.state.last_asked_field='order_details'
                answer='ขอทราบ'+ ' และ '.join(missing)+'ครับ บอกการแพ้อาหาร ความชอบ และเครื่องดื่มพร้อมกันได้เลย ไม่รับของหวานจะไม่เพิ่มให้ครับ'
                self.state.add_message('assistant',answer)
                return answer
            warning=self.intake_budget_warning()
            if warning:
                self.state.add_message('assistant',warning)
                return warning
            if self.state.wants_dessert and not self.state.dessert_selection:
                self.pending_confirmation=False
                self.state.last_asked_field='dessert_selection'
                answer=self.open_extras('ของหวาน')
                self.state.add_message('assistant',answer)
                return answer
            if not self.details_confirmed or extracted.get('allergens') or self.pending_allergy_removals:
                self.pending_confirmation=True
                self.state.last_asked_field='order_confirmation'
                answer=self.order_summary()
                self.state.add_message('assistant',answer)
                return answer
            self.pending_confirmation=False
            self._replan=not explicit_search
        try:
            answer=asyncio.run(self._run(user_message,extracted.get('budget_change_unclear',False)))
        except Exception as exc:
            cause=_root_cause(exc)
            self.last_run.setdefault('model_errors',[]).append(model_error(cause,'planning'))
            LOG.exception('agent turn failed: %s',type(cause).__name__)
            self.clear_choices()
            self.last_trace.append({'step':'turn','error':f'{type(cause).__name__}: {str(cause)[:300]}'})
            answer='ผู้ช่วยไม่พร้อมชั่วคราว กรุณาลองอีกครั้งครับ ข้อมูลความต้องการเดิมยังอยู่'
        self.state.add_message('assistant',answer)
        self.state.conversation=self.state.conversation[-24:]
        return answer


    def chat(self,user_message):
        started=time.perf_counter()
        self.last_run={'session_id':self.session_id,'turn_id':str(uuid4()),
            'created_at':datetime.now(timezone.utc).isoformat(),'model_source':self.model_source,
            'model':self.model_name,'model_calls':0,'usage_responses':0,
            'usage':{'input_tokens':0,'output_tokens':0,'total_tokens':0}}
        answer=self._chat(user_message)
        if self.state.allergens and ALLERGY_WARNING not in answer:
            answer+='\n\n'+ALLERGY_WARNING
        self.last_run['data_mode']=self.data_mode
        self.last_run['allergy_simulation_consent']=self.allergy_simulation_consent
        self.last_run['elapsed_ms']=round((time.perf_counter()-started)*1000,3)
        self.last_run['tool_calls']=len(self.last_trace)+len(self.last_run.get('option_checks',[]))
        self.last_run['token_usage_complete']=self.last_run['usage_responses']==self.last_run['model_calls'] and self.last_run['model_calls']>0
        self.last_run['outcome']='recommendation' if self.state.last_result else 'no_recommendation'
        self.last_trace=redact(self.last_trace)
        return answer


    def chat_stream(self,user_message) -> Iterator[str]:
        """Buffer output until policy validation finishes; no early unsafe chunks."""
        yield self.chat(user_message)
