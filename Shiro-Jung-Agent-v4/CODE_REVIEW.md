# Code Review — Shiro-Jung 4.2.1

## ผล Live LLM ที่ตรวจหลักฐานแล้ว

[GitHub Actions run 39799552734](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39799552734) ใช้ source commit **426b48a** และโมเดลที่ตั้งค่า **gpt-4o-mini** รายงานสร้างวันที่ **22 ตุลาคม 2569 เวลา 21:53 น. (Asia/Bangkok)** ตรวจจาก ZIP ที่ผู้ใช้ส่ง ไม่ได้รัน API ใหม่จากเครื่องนี้

| ตัวชี้วัด | ผลจริง |
|---|---|
| Live / gold success | `live_llm_tested=true`, `success_rate=1.0` — ผ่าน 12/12 gold turns ใน 5 sessions |
| ประเภทผลที่คาดหวัง | แนะนำอาหาร 6, block 4, clarification 2 |
| Actual conversation turns | 18 รวมการยืนยันข้อมูลอัตโนมัติของ runner |
| Successful model responses | 31; model errors 0 |
| Model-selected recommendations | 6 — ตรวจ `route=model_selected` ของ build_set และ verify_set ที่ passed และ result_id ตรงกัน |
| Tokens จาก provider metadata | input 113,459 + output 2,548 = 116,007; ไม่คำนวณค่าเงินโดยไม่มีราคาที่อ้างอิง |

หลักฐานต้นฉบับและ SHA256 อยู่ใน [live evidence](artifacts/live-confirmed-39799552734/README.md) พร้อม [trace หนึ่ง session](artifacts/live-confirmed-39799552734/live-trace.md) สำหรับนำเสนอ ผล 100% จำกัดอยู่ที่ corpus นี้ ไม่ใช่การรับรองภาษาไทยทุกกรณี ความพึงพอใจ หรือสูตรอาหารของร้าน

**ข้อจำกัดการบันทึกที่พบ:** ลิสต์ใน `turn.state` ของ artifact เดิมอาจถูกเติมด้วยข้อมูลรอบหลัง จึงเก็บต้นฉบับไว้และแสดง historical constraints จาก `build_set.arguments` ของรอบเดียวกันใน trace ที่สร้างใหม่ แก้ runner ให้ deep-copy snapshot และแก้ parser ไม่ตี “เงื่อนไขอื่นเหมือนเดิม” เป็นอาหารแล้ว การแก้สองจุดนี้ทดสอบ offline หลัง live commit ไม่อ้างว่าเป็น live rerun ชุดใหม่ ราคา/สารก่อภูมิแพ้ยัง unverified/unknown ทั้ง 42 รายการ และยังไม่มี persistence ข้าม session

## ตรวจรูปแบบ API key ก่อนเรียก provider

`credentials.clean_api_key` ตัด whitespace และอักขระ clipboard ที่ขอบ พร้อมแกะเครื่องหมายคำพูดครอบ (รวม smart quotes/ข้างเดียว), `Bearer ` หรือ `OPENAI_API_KEY=` ที่นำหน้าคีย์ค่าเดียว ร่วมกันทั้ง Agent และ live runner ไม่ต่อหลายบรรทัดเข้าด้วยกันหรือแก้เนื้อหาคีย์ภายใน หากยังมี newline/ช่องว่างแทรก/อักขระแฝง/ข้อความตั้งค่าอื่น จะหยุดก่อน HTTP ด้วย `blocked_invalid_credential_format` และแสดง `credential_format_issues` เฉพาะชื่อสาเหตุ ไม่แสดงคีย์ การตรวจนี้ไม่พิสูจน์สิทธิ์หรือเครดิต API

หาก job log มี `Illegal header value` ให้แก้ repository Secret `OPENAI_API_KEY` เป็นค่าคีย์บรรทัดเดียว ไม่รวมชื่อ environment variable หรือเครื่องหมายคำพูด จากนั้นเริ่ม **Run workflow ใหม่บน main** เพื่อใช้ commit ล่าสุด ค่า `***` ใน GitHub log เป็นการ mask secret ไม่ใช่หลักฐานว่าค่าคีย์จริงคือดอกจัน

ตรวจ targeted 11 เคส: credential normalization/redaction 4, provider diagnostics 5, consumer live-runner harness 2 ผ่านโดยไม่เรียก API จริง โดย snapshot ก่อนหน้ามี 165 เคส และ targeted credential checks 11 เคส; รอบปัจจุบันรัน full suite อีกครั้งหลังแก้ snapshot/exporter/parser รายละเอียดใน artifacts/review-round2-credential-check/clipboard-targeted-checks.json

## วินิจฉัยการเรียก provider ใน GitHub Actions

`executed_turns` นับรอบสนทนาที่ runner ลองทำ ไม่ใช่จำนวนคำตอบที่ API ส่งกลับสำเร็จ ดู `successful_model_responses`, `model_error_count` และ `error_categories` เพิ่มเติม `live_llm_tested` ยังต้องมี successful real-provider response จึงเป็น true; ไม่ตั้ง true จากการมี API key เพียงอย่างเดียว

Agent บันทึกเฉพาะ phase, exception type, HTTP status และ provider error code ที่อนุญาต โดยไม่ export raw exception/body/header หรือ key แยก authentication (401), quota/billing (`insufficient_quota`), rate limit (429), model access, permission, timeout, connection และ invalid extraction response ในรายงานหลังบ้าน ไม่แสดงรายละเอียดเหล่านี้ในแชตผู้บริโภค

เมื่อไม่มี successful provider response และมี error จะรายงาน `failed_no_successful_model_response` แทน completed; หากรันแล้วมี gold failures ใช้ `completed_with_failures` ส่วน job summary แนะนำการตรวจ Secret หรือ API billing ตาม category ที่ตรวจได้ ไม่เดาสาเหตุจากภาพ success_rate=0 อย่างเดียว คำตอบ JSON ที่ไม่ผ่าน schema ยังนับว่าได้รับ response แต่ไม่ผ่านงาน

## ข้อแก้ไขเร่งด่วนหลังทดสอบเว็บจริง

| จุดตรวจ | ผลแก้ไข / ขอบเขต |
|---|---|
| Hard refusal | `restrictions.py` ถูกเรียกจาก sanitizer รวม narrow-context/direct extraction paths; ไม่กิน/ไม่ทาน/งด/ห้าม สร้าง hard keywords แม้โมเดลส่ง dislike; `BudgeteerState` ลบ soft alias ซ้ำกับ hard เดิม |
| Soft preference | “ไม่ค่อยชอบหมู” ยังเป็น dislike ไม่สร้าง hard ใหม่และไม่ล้างข้อห้ามเดิมโดยปริยาย |
| Alternative | `MenuService.alternative` ตัด `ceil(0.30 × distinct original food dishes)` เริ่มกลุ่มคะแนนสูงสุด ลอง ≤3 กลุ่ม ตรวจสัดส่วนชื่อเดิมที่หายไปจริง ไม่รวม fixed extras; ไม่มีชุดที่ผ่านให้ unavailable แทนชุดใกล้ซ้ำ |
| Live evidence gate | workflow manual, secret ผ่าน env เฉพาะ live step; runner ตรวจ state/budget/allergy เพิ่มเติม นับ model-selected recommendation เฉพาะ successful real-provider run; exporter ปฏิเสธ scripted/fallback |
| Evidence status | importer รองรับ team_reviewed พร้อมเหตุผล ผู้ตรวจ วันที่; strict ยังคงต้อง confirmed; confirmed price ต้องมี source/date |
| Persistence | ยังไม่ทำ เก็บเป็นข้อจำกัดใน README/EVALUATION/สไลด์; SQLite ปัจจุบันเก็บ menu catalog ไม่ใช่ durable conversation |

10 regression cases ใหม่ใน `test_explicit_refusals.py` รวมข้อความที่ผู้ใช้ทดสอบบนเว็บ, 4 cases ใน `test_evidence_status.py` และ 3 cases ใน `test_live_trace_export.py` (synthetic fixtures ไม่ใช่ live evidence) ผลทั้งหมดดู validation JSON ล่าสุด

ตรวจ implementation รอบแก้ไข 2 วันที่ 22 ตุลาคม 2569 ครอบคลุมกฎปฏิเสธอาหารแบบ hard ที่ไม่ขึ้นกับ LLM, ความต่างของชุดอาหาร ≥30%, workflow หลักฐาน live, สถานะ team_reviewed และโครงสร้าง Agent เอกสารนี้แทนคำอธิบายโครงสร้างรุ่นก่อน ผลรันใหม่แยกใน `artifacts/review-round2-followup/` ส่วนผลเดิมไม่ถูกเขียนทับ

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

## โครงสร้างหลัง refactor

| โมดูล | ความรับผิดชอบ |
|---|---|
| `agent.py` / `BudgeteerAgent` | lifecycle, reset, usage/report และการ route ข้อความ |
| `intake.py` / `IntakeMixin` | Extraction schema, missing fields, สรุปยืนยัน, เลือกชนิดเนื้อ และข้อความอธิบายข้อจำกัด |
| `planning.py` / `PlanningMixin` | bounded LLM/MCP loop, fallback, alternative generation และ verify ก่อนแสดง |
| `checkout.py` / `CheckoutMixin` | extra menu parsing, ตะกร้า, เลือกชุด, รวมยอด และยืนยัน |
| `restrictions.py`, `meat_scope.py`, `dietary.py` | แยกความหมายคำกว้างและชนิดเนื้อจากการจับคำและการกรอง tags |

`BudgeteerAgent` ยังเป็น API เดิมที่รวม mixins และถือ session state จุดเดียว ไม่สร้าง global conversation store ไม่อ้างว่าลดความซับซ้อนทั้งหมดด้วยการย้ายไฟล์ มี regression เดิมครบและเพิ่มกรณี meat clarification/clinical ingredient guards

## ผลตรวจตามองค์ประกอบ

| ประเด็น | การทำงานและหลักฐาน |
|---|---|
| Session isolation | `app.py` เก็บ Agent ใน `st.session_state`; ไม่มี shared cached conversation; ตรวจใน `test_system.py` |
| Consumer intake | `consumer_flow=True` รวมข้อมูลมื้อและสรุปยืนยันครั้งเดียว ไม่บังคับถามน้ำ/ขนมทีละช่อง; `test_short_order.py` |
| Planning / replan | ผ่าน model tool loop จริงในเชิง implementation; constraint snapshot เขียนทับ arguments ที่โมเดลเสนอ; `test_review_round1.py` |
| Output gate | `MenuService` เก็บ candidate ด้วย UUID ตรวจจาก SQLite ใหม่ แล้วบังคับ Python ผ่านและ OPA allow; ไม่ปล่อย unverified model prose เป็นชุดอาหาร |
| เลือกชนิดเนื้อ | คำกว้างไม่ชอบ/ไม่กิน/แพ้เนื้อเปิดตัวเลือกหมู วัว ไก่ ทั้งหมด โดยจำความสัมพันธ์และมื้อเดิม; `test_round2_meat_scope.py` |
| Dietary exclusions | `dietary.py` ใช้ exact tags สำหรับข้อห้ามที่รู้จัก เช่น raw/pork; ชื่ออื่นใช้ literal match; fuzzy อยู่ใน search/soft preferences |
| Allergens | ใช้ `allergen_tags`; strict ต้องมี confirmed evidence; unknown ไม่ใช่ absent; seafood ขยายเป็น fish/crustacean/molluscs/echinoderm |
| Allergy opt-in | หลังยืนยันข้อมูลแล้ว strict จัดไม่ได้เพราะหลักฐานไม่พอ ผู้ใช้เลือก “ดูชุดจำลองจากข้อมูลเมนู” เพื่อวางแผน; เก็บการแพ้เดิม กรองทุกหมวด และแสดงคำเตือน |
| ขอบเขต opt-in | เป็นสถานะต่อมื้อ ไม่เปลี่ยน environment หรือสถานะร้าน; รักษาผ่าน Streamlit rerun; reset กลับค่า deployment; unknown allergen ไม่เปิดทางเลือก; `test_allergy_simulation_optin.py` ทั้ง 6 กรณี |
| Extras / checkout | คงอาหารที่เลือก เพิ่มหรือแก้จำนวนด้วย item ID ตรวจใหม่กับ catalog ปัจจุบัน; รวมยอดทุกหมวดไม่เกินงบเต็ม; `test_checkout_sequence.py`, `test_short_menu_names.py` |
| OPA | `package shiro`, policy `shiro-4.2`, schema 2; Rego เทียบ raw allergen/dietary tag sets เอง ทดสอบเมื่อ Python flags เป็น false และ fail closed เมื่อ binary หาย |
| Catalog migration | รองรับ CSV/SQLite ชื่อคอลัมน์เดิม เพิ่ม dietary/10-group mapping โดยรักษาราคาและ provenance; `test_review_round1.py`, `test_thai_allergen_groups.py` |
| Consumer UI | แสดงรายการ ราคา ยอดรวม เงินเหลือ และตัวเลือกที่เกี่ยวข้อง; คะแนน ที่มา OPA และ trace อยู่หลังบ้าน |

## Objective และ benchmark

การจัดอาหารใช้ bounded exact DP บน `(count, cost_satang)` ขยายได้สูงสุด 3 สำเนาต่อเมนู จานซ้ำได้คะแนนส่วนเพิ่ม `1, 0.5, 0.25` เท่าของคะแนนพื้นฐาน มี GCD ลดมิติราคาและ state limit 250,000

คะแนนพื้นฐานคือ `max(0, preference + price_tier + category_weight - dislike_penalty)` โดย preference สูงสุด 5, price tier 3/2/1, category weight +2 เมื่อหมวดไม่ใช่ปลาดิบ และ dislike penalty 3 ตัว category weight เป็น heuristic เดิม ไม่ใช่ category coverage ของทั้งชุด ความใกล้งบอยู่ใน objective ระดับชุด

ค่าร่วมใน `optimization_config.py`: `objective=budget`, `diversity=True`, `INITIAL_SPEND_RATIO=0.8`, อาหารสูงสุด 60 รายการเมื่อผู้ใช้ไม่ได้กำหนดต่ำกว่านั้น และ repeat cap 3 หากมีชุดใช้วงเงินอาหารได้อย่างน้อย 95% จะเลือกคะแนนลดซ้ำสูงสุดแล้ว spend เป็น tie break; ถ้าไม่มี จะเลือก spend สูงสุดก่อนแล้วคะแนน

กฎ 80/20 เป็นข้อกำหนดผลิตภัณฑ์เพื่อเหลือเงินเพิ่มรายการ ไม่ใช่ข้อพิสูจน์ว่าอร่อย อิ่ม หรือคุ้มที่สุดทุกมิติ Checkout ตรวจยอดกับงบเต็มอีกครั้ง อาหารไม่เกิน 60 น้ำไม่เกิน 60 และขนมไม่เกิน 60 เมื่อไม่ได้มีเพดานรวมที่ผู้ใช้กำหนดเอง

ดู `artifacts/review-round2-followup/benchmark-production.json`: 12 สถานการณ์, Random 1,200 ครั้ง, ไม่มี feasibility หรือ objective-dominance failure ในชุดนี้ DP ใช้งบเต็มเฉลี่ย 76.25% / วงเงินอาหาร 95.3125% ขณะที่ Greedy density ได้คะแนนและจำนวนหมวดเฉลี่ยสูงกว่า จึงไม่อ้าง raw-score หรือ diversity dominance ผลนี้วัดอาหารเริ่มต้น ไม่รวม LLM, allergy, extras หรือความพึงพอใจจริง

## หลักฐานปัจจุบัน

| หลักฐาน | ผล / แหล่งข้อมูล |
|---|---|
| Regression / integration | 165 tests, failures 0, errors 0 — `artifacts/review-live-confirmed-checks/validation-report.json` |
| OPA / Rego | 25 tests ผ่าน — `artifacts/review-live-confirmed-checks/opa-tests.json` |
| Smoke | strict 61 และ simulation 61 ผ่าน — log ใน `artifacts/review-round2-followup/` |
| Offline gold | 40/40 — `artifacts/review-round2-followup/offline-evaluation.json`; ไม่มี LLM |
| Consumer planning trace | `artifacts/review-round2-followup/scripted-consumer-trace.json`; scripted model + real MCP/SQLite/OPA แยกจาก live evidence จริงข้างต้น |
| Live consumer sessions | `completed`, 12/12 gold, 18 actual turns, 31 responses, 6 model-selected recommendations — `artifacts/live-confirmed-39799552734/live-sessions.json`, source 426b48a |

รอบนี้รัน regression ใหม่หลังแก้ snapshot/exporter/parser ส่วน benchmark ใช้ snapshot production config เดิมที่ยังไม่เปลี่ยน objective ดูเวลาจริงจาก `checked_at` / `created_at` ใน artifacts ดูคำสั่งและขอบเขตใน [EVALUATION.md](EVALUATION.md)

## ประเด็นที่ยังเปิดอยู่

| ระดับ / ประเด็น | ผลกระทบและงานต่อ |
|---|---|
| กลาง: ขอบเขต live ยังจำกัด | ผ่าน 5 sessions/12 gold turns ที่ commit 426b48a; ยังต้องทดสอบนอก corpus/human review; reporting/parser patch หลังจากนั้นยังไม่ใช่ live rerun |
| สำคัญ: สูตรร้านยัง unknown | 42 เมนูราคา unverified และ allergen unknown; ทะเบียนฉลาก 10 กลุ่มไม่ใช่หลักฐานสูตร การใช้ชุดจำลองไม่รับรองความปลอดภัยแพ้อาหารหรือการปนเปื้อน |
| กลาง: MCP subprocess ต่อ turn | เพิ่มเวลาเปิด process และ verify หลายรอบ ต้องวัด latency จริงก่อนเปลี่ยน lifecycle/session reuse |
| กลาง: ไม่มี persistence/auth | ความจำอยู่ใน session ไม่รองรับการกู้คืนหลัง restart หรือระบบบัญชีผู้ใช้ |
| กลาง: legacy CLI ต่างจากหน้าเว็บ | `__main__.py` สร้าง `BudgeteerAgent()` โดยไม่เปิด consumer flow; `/reset` ปัจจุบันเรียก `state.reset()` ไม่ใช่ `reset_order()` จึงไม่ควรอ้างว่ารีเซ็ต workflow ทุกส่วนเหมือนเว็บ |
| กลาง: ปริมาณและ objective | `num_people` ยังไม่ใช่โมเดล portion/ความอิ่ม; category weight ยังเป็น heuristic; ไม่รวมภาษีและ service charge |
| การบำรุงรักษา | แยก intake/planning/checkout เป็น mixins แล้ว ยังใช้ shared session state และมี coupling ข้ามหน้าที่ ควรพิจารณา composition ภายหลังโดยรักษา API/guards |

`rag.py` เป็นส่วนทดลอง ไม่เปิดใน MCP ของเส้นทางหลัก; legacy direct tools มี thread-local last-result compatibility ส่วน Agent/MCP ใช้ server-held result IDs รายงานนี้ไม่อ้างว่าทดสอบ Windows/macOS, public deployment หรือ RAG กับ provider จริงแล้ว
