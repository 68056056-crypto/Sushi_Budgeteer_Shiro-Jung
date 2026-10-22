# Code Review — Shiro-Jung 4.1.0

ตรวจเอกสารเทียบ implementation ที่ commit `6b420b7` วันที่ 22 ตุลาคม 2569 เอกสารฉบับนี้แทนรายงานรุ่น 3.0/4.0 และสะท้อนเส้นทางหน้าเว็บหลังเพิ่ม allergy simulation opt-in ไม่ได้อ้างว่ามีการประเมินโมเดลจริงหรือข้อมูลร้านเพิ่มขึ้นในรอบเอกสารนี้

## โมเดลและขอบเขตการตัดสินใจ

| ส่วน | Implementation ปัจจุบัน |
|---|---|
| LLM เริ่มต้น | OpenAI `gpt-4o-mini` ผ่าน LangChain `ChatOpenAI`; เปลี่ยนด้วย `OPENAI_MODEL` หรือการตั้งค่าโมเดลใน Streamlit secrets |
| Provider settings | `temperature=0`, timeout 30 วินาที, `max_retries=1` |
| Extraction | โมเดลสกัด JSON แล้วตรวจด้วย Pydantic และ contextual-answer guards ก่อนอัปเดต `BudgeteerState` |
| Planning | หลังผู้ใช้ยืนยันข้อมูลหรือขอปรับชุด ใช้ `bind_tools` เลือก MCP tool จาก state และ observation สูงสุด 10 model rounds, 8 calls ต่อรอบ |
| ข้อจำกัด | `build_set` ใช้ arguments จาก state; `verify_set` รับเฉพาะ candidate ของ turn ปัจจุบัน โมเดลปลดการแพ้หรือเพิ่มงบเองไม่ได้ |
| Fallback | เมื่อโมเดลไม่เลือก tool สองครั้ง อาจใช้ build/verify หรือ clarify ที่โค้ดควบคุม; trace ระบุ `after_stall` แยกจาก `route=model_selected` |
| งานที่ใช้โค้ดโดยตรง | คำตอบสั้นที่มีบริบท, การเลือกชุด, อ่านชื่อย่อและจำนวนส่วนเพิ่ม, สรุป/ยืนยัน/รีเซ็ต; การสร้างทางเลือกชุดที่สองและ recheck อยู่ใน orchestration |

โมเดลนี้ใช้ prompt, state และ tools ของโครงการ ไม่มีหลักฐานการ fine-tune หรือฝึก weights ใหม่ใน repository `temperature=0` ไม่ใช่หลักประกันว่าผล provider จะเหมือนกันทุกครั้ง ต้องแยกความถูกต้องของการต่อวงจรออกจากคุณภาพการตัดสินใจของ live LLM

## ผลตรวจตามองค์ประกอบ

| ประเด็น | การทำงานและหลักฐาน |
|---|---|
| Session isolation | `app.py` เก็บ Agent ใน `st.session_state`; ไม่มี shared cached conversation; ตรวจใน `test_system.py` |
| Consumer intake | `consumer_flow=True` รวมข้อมูลมื้อและสรุปยืนยันครั้งเดียว ไม่บังคับถามน้ำ/ขนมทีละช่อง; `test_short_order.py` |
| Planning / replan | ผ่าน model tool loop จริงในเชิง implementation; constraint snapshot เขียนทับ arguments ที่โมเดลเสนอ; `test_review_round1.py` |
| Output gate | `MenuService` เก็บ candidate ด้วย UUID ตรวจจาก SQLite ใหม่ แล้วบังคับ Python ผ่านและ OPA allow; ไม่ปล่อย unverified model prose เป็นชุดอาหาร |
| Dietary exclusions | `dietary.py` ใช้ exact tags สำหรับข้อห้ามที่รู้จัก เช่น raw/pork; ชื่ออื่นใช้ literal match; fuzzy อยู่ใน search/soft preferences |
| Allergens | ใช้ `allergen_tags`; strict ต้องมี confirmed evidence; unknown ไม่ใช่ absent; seafood ขยายเป็น fish/crustacean/molluscs/echinoderm |
| Allergy opt-in | หลังยืนยันข้อมูลแล้ว strict จัดไม่ได้เพราะหลักฐานไม่พอ ผู้ใช้เลือก “ดูชุดจำลองจากข้อมูลเมนู” เพื่อวางแผน; เก็บการแพ้เดิม กรองทุกหมวด และแสดงคำเตือน |
| ขอบเขต opt-in | เป็นสถานะต่อมื้อ ไม่เปลี่ยน environment หรือสถานะร้าน; รักษาผ่าน Streamlit rerun; reset กลับค่า deployment; unknown allergen ไม่เปิดทางเลือก; `test_allergy_simulation_optin.py` ทั้ง 6 กรณี |
| Extras / checkout | คงอาหารที่เลือก เพิ่มหรือแก้จำนวนด้วย item ID ตรวจใหม่กับ catalog ปัจจุบัน; รวมยอดทุกหมวดไม่เกินงบเต็ม; `test_checkout_sequence.py`, `test_short_menu_names.py` |
| OPA | `package shiro`, policy `shiro-4.1`, schema 2; Rego เทียบ raw allergen/dietary tag sets เอง ทดสอบเมื่อ Python flags เป็น false และ fail closed เมื่อ binary หาย |
| Catalog migration | รองรับ CSV/SQLite ชื่อคอลัมน์เดิม เพิ่ม dietary/10-group mapping โดยรักษาราคาและ provenance; `test_review_round1.py`, `test_thai_allergen_groups.py` |
| Consumer UI | แสดงรายการ ราคา ยอดรวม เงินเหลือ และตัวเลือกที่เกี่ยวข้อง; คะแนน ที่มา OPA และ trace อยู่หลังบ้าน |

## Objective และ benchmark

การจัดอาหารใช้ bounded exact DP บน `(count, cost_satang)` ขยายได้สูงสุด 3 สำเนาต่อเมนู จานซ้ำได้คะแนนส่วนเพิ่ม `1, 0.5, 0.25` เท่าของคะแนนพื้นฐาน มี GCD ลดมิติราคาและ state limit 250,000

คะแนนพื้นฐานคือ `max(0, preference + price_tier + category_weight - dislike_penalty)` โดย preference สูงสุด 5, price tier 3/2/1, category weight +2 เมื่อหมวดไม่ใช่ปลาดิบ และ dislike penalty 3 ตัว category weight เป็น heuristic เดิม ไม่ใช่ category coverage ของทั้งชุด ความใกล้งบอยู่ใน objective ระดับชุด

ค่าร่วมใน `optimization_config.py`: `objective=budget`, `diversity=True`, `INITIAL_SPEND_RATIO=0.8`, อาหารสูงสุด 60 รายการเมื่อผู้ใช้ไม่ได้กำหนดต่ำกว่านั้น และ repeat cap 3 หากมีชุดใช้วงเงินอาหารได้อย่างน้อย 95% จะเลือกคะแนนลดซ้ำสูงสุดแล้ว spend เป็น tie break; ถ้าไม่มี จะเลือก spend สูงสุดก่อนแล้วคะแนน

กฎ 80/20 เป็นข้อกำหนดผลิตภัณฑ์เพื่อเหลือเงินเพิ่มรายการ ไม่ใช่ข้อพิสูจน์ว่าอร่อย อิ่ม หรือคุ้มที่สุดทุกมิติ Checkout ตรวจยอดกับงบเต็มอีกครั้ง อาหารไม่เกิน 60 น้ำไม่เกิน 60 และขนมไม่เกิน 60 เมื่อไม่ได้มีเพดานรวมที่ผู้ใช้กำหนดเอง

ดู `artifacts/benchmark-production.json`: 12 สถานการณ์, Random 1,200 ครั้ง, ไม่มี feasibility หรือ objective-dominance failure ในชุดนี้ DP ใช้งบเต็มเฉลี่ย 76.25% / วงเงินอาหาร 95.3125% ขณะที่ Greedy density ได้คะแนนและจำนวนหมวดเฉลี่ยสูงกว่า จึงไม่อ้าง raw-score หรือ diversity dominance ผลนี้วัดอาหารเริ่มต้น ไม่รวม LLM, allergy, extras หรือความพึงพอใจจริง

## หลักฐานปัจจุบัน

| หลักฐาน | ผล / แหล่งข้อมูล |
|---|---|
| Regression / integration | 127 tests, failures 0, errors 0 — `artifacts/review-round1/validation-report.json` |
| OPA / Rego | 24 tests ผ่าน — `artifacts/review-round1/opa-tests.json` |
| Smoke | strict 61 และ simulation 61 ผ่าน — log ใน `artifacts/review-round1/` |
| Offline gold | 40/40 — `artifacts/review-round1-offline-evaluation.json`; ไม่มี LLM |
| Consumer planning trace | `artifacts/review-round1-scripted-consumer-trace.json`; scripted model + real MCP/SQLite/OPA |
| Live consumer sessions | `artifacts/review-round1-live-status.json`: `blocked_missing_credentials`, 0 turns |

รายงาน regression รันวันที่ 22 ตุลาคม 2569 เวลา 17:40 น. ประเทศไทย การแก้เอกสารครั้งนี้ไม่ใช่การรันทดสอบแอปซ้ำ ดูคำสั่งและขอบเขตใน [EVALUATION.md](EVALUATION.md)

## ประเด็นที่ยังเปิดอยู่

| ระดับ / ประเด็น | ผลกระทบและงานต่อ |
|---|---|
| สำคัญ: live LLM ยังไม่มีหลักฐาน | Default model เป็นค่าตั้งต้นของโค้ด ไม่ใช่หลักฐานว่า deployment ใช้ค่านั้นหรือผ่านการทดสอบ ต้องรัน consumer sessions และตรวจ tool selection, extraction, fallback, tokens และ latency จริง |
| สำคัญ: สูตรร้านยัง unknown | 42 เมนูราคา unverified และ allergen unknown; ทะเบียนฉลาก 10 กลุ่มไม่ใช่หลักฐานสูตร การใช้ชุดจำลองไม่รับรองความปลอดภัยแพ้อาหารหรือการปนเปื้อน |
| กลาง: MCP subprocess ต่อ turn | เพิ่มเวลาเปิด process และ verify หลายรอบ ต้องวัด latency จริงก่อนเปลี่ยน lifecycle/session reuse |
| กลาง: ไม่มี persistence/auth | ความจำอยู่ใน session ไม่รองรับการกู้คืนหลัง restart หรือระบบบัญชีผู้ใช้ |
| กลาง: legacy CLI ต่างจากหน้าเว็บ | `__main__.py` สร้าง `BudgeteerAgent()` โดยไม่เปิด consumer flow; `/reset` ปัจจุบันเรียก `state.reset()` ไม่ใช่ `reset_order()` จึงไม่ควรอ้างว่ารีเซ็ต workflow ทุกส่วนเหมือนเว็บ |
| กลาง: ปริมาณและ objective | `num_people` ยังไม่ใช่โมเดล portion/ความอิ่ม; category weight ยังเป็น heuristic; ไม่รวมภาษีและ service charge |
| การบำรุงรักษา | Agent class รวมหลายหน้าที่; ควรแยก intake, planning และ checkout พร้อมรักษา regression และ trust boundary เดิม |

`rag.py` เป็นส่วนทดลอง ไม่เปิดใน MCP ของเส้นทางหลัก; legacy direct tools มี thread-local last-result compatibility ส่วน Agent/MCP ใช้ server-held result IDs รายงานนี้ไม่อ้างว่าทดสอบ Windows/macOS, public deployment หรือ RAG กับ provider จริงแล้ว
