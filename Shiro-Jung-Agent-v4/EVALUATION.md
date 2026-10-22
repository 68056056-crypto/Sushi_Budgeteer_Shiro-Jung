# Evaluation — Shiro-Jung 4.1.0

อ้างอิง implementation `6b420b7` และ artifacts ล่าสุดที่ระบุด้านล่าง ตรวจความสอดคล้องเอกสารวันที่ 22 ตุลาคม 2569 ไม่มีการสร้างผล live หรือ rerun benchmark เพื่อปรับตัวเลขในรอบเอกสารนี้

## โมเดลและวิธีทดสอบ

โมเดลเริ่มต้นคือ OpenAI `gpt-4o-mini` ผ่าน `ChatOpenAI`, `temperature=0`, timeout 30 วินาที, `max_retries=1` เปลี่ยนโมเดลด้วย `OPENAI_MODEL` หรือการตั้งค่า Streamlit การระบุชื่อ default ไม่ยืนยันว่าการ deploy ใช้ค่านั้น ให้ตรวจ `model` และ `model_source` ใน run report ของการเรียกจริง

| ชั้นการประเมิน | สิ่งที่รัน / ผลล่าสุด | ขอบเขต |
|---|---|---|
| Regression / integration | 127 tests ผ่าน | scripted model + real MCP subprocess, SQLite, OPA และ Streamlit AppTest |
| OPA / Rego | 24/24 | ตรวจกฎแยก รวม raw-tag conflicts และ fail closed |
| Smoke | strict 61/61, simulation 61/61 | โหมด strict ต้องปฏิเสธการแพ้เมื่อ evidence ไม่พอ ไม่ลดโหมดเพื่อให้ผ่าน |
| Offline gold | 40/40 | ไม่มีโมเดล; ทดสอบ tools/constraints บน seed catalog |
| Production benchmark | 12 กรณี, Random 1,200 ครั้ง | objective/config เดียวกับอาหารเริ่มต้นบนเว็บ |
| Live single-turn | ยังไม่มีผลรัน | runner ใช้ legacy Agent readiness ไม่ใช่ consumer opt-in flow |
| Live consumer sessions | `blocked_missing_credentials`, 0 turns | runner พร้อม 3 sessions / 7 gold turns; intake อาจเพิ่ม confirmation calls |
| Consumer allergy opt-in | 6 regression tests ผ่าน | ยังไม่มีผล live opt-in session |

ผล regression ที่บันทึกไว้วันที่ 22 ตุลาคม 2569 เวลา 17:40 น. ประเทศไทย อยู่ใน `artifacts/review-round1/validation-report.json` จำนวน tests และผล scripted ไม่รับรองคุณภาพภาษาไทยของ live model หรือความปลอดภัยของสูตรร้าน

## แหล่งหลักฐานที่ใช้

| ไฟล์ | หน้าที่ |
|---|---|
| `artifacts/review-round1/validation-report.json` | จำนวน tests, failures/errors, Python/platform, smoke modes และสถานะ live |
| `artifacts/review-round1/opa-tests.json` | ผล Rego 24 กรณี |
| `artifacts/review-round1/smoke-strict.log`, `smoke-simulation.log` | ผล smoke รายโหมด |
| `artifacts/review-round1-offline-evaluation.json` | 40 gold outcomes, catalog revision และ offline metrics |
| `artifacts/benchmark-production.json` | config, ผลทุกวิธี, Random seeds และตัวชี้วัดรายกรณี |
| `artifacts/review-round1-scripted-consumer-trace.json` | หลักฐานต่อวงจร consumer planning/replan ด้วย scripted model; ไม่ใช่ live |
| `artifacts/review-round1-live-status.json` | สถานะ live consumer sessions |
| `artifacts/live-evaluation.json` | สถานะ/ผลของ single-turn live runner เมื่อรันจริง |
| `artifacts/review-round1-report.html` | รายงานที่สร้างจาก JSON ข้างต้น; ไม่รันทดสอบเอง |

`artifacts/validation-report.json`, `opa-tests.json`, `offline-evaluation.json`, `live-sessions.json` และ `benchmark.json` ชื่อเดิมเป็น snapshot รุ่นก่อน อย่านำตัวเลขมารวมกับผลล่าสุดโดยไม่ตรวจวันที่ ขอบเขต และ revision หน้าแชตไม่แสดงตาราง technical evidence หรือปุ่มดาวน์โหลด trace; ใช้ backend `agent.run_report()` และสคริปต์รายงาน

## ทำซ้ำแบบ offline

รันจาก `Shiro-Jung-Agent-v4` หลังติดตั้ง dependencies และ OPA โดยไม่ต้องมี API key:

```bash
python scripts/install_opa.py
python scripts/run_checks.py --output-dir artifacts/review-round1
python scripts/evaluate.py --mode offline --output artifacts/review-round1-offline-evaluation.json
python scripts/benchmark.py
python scripts/build_report.py
```

เปิด `artifacts/review-round1-report.html` ใน browser เพื่อดูผลและเลือก benchmark รายสถานการณ์ การสร้าง HTML อ่าน artifacts ที่มีอยู่ ไม่อัปเดตผลทดสอบหรือเติมผลที่ยังไม่มี

อีกทางคือ `python scripts/collect_evidence.py --offline` ซึ่งรวมหลายขั้น **แต่จะ import CSV ทับ runtime catalog ด้วย** Import เป็น replace ไม่ใช่ merge หากฐานข้อมูลมีราคา/หลักฐานร้านที่ปรับเอง ให้สำรองและใช้คำสั่งแยกข้างต้นแทนเมื่อไม่ต้องการ replace catalog

`evaluation/cases.json` มี 40 กรณี ครอบคลุมงบ ความชอบ hard exclusions, only-food, จำนวน น้ำ/ขนม strict/simulation, unknown evidence และ invalid inputs ต้องทบทวน expectations เมื่อเปลี่ยน catalog ไม่แก้ expected outcome เพื่อซ่อน defect Min/max ของ direct builder นับทุกหมวดรวมเครื่องดื่มฟรีด้วย และต้องมีอาหารอย่างน้อย 1 จาน

## สิ่งที่ตรวจใน consumer flow ปัจจุบัน

1. รับข้อมูลมื้อและสรุปยืนยันครั้งเดียว ไม่บังคับน้ำหรือขนมก่อนจัดอาหาร
2. หลังยืนยันและ replan ให้ LLM เลือก tool โดย state เป็นเจ้าของข้อจำกัด ตรวจ candidate ของ turn ปัจจุบันก่อนแสดงสูงสุด 2 ชุด
3. Strict + unknown recipe evidence ไม่เสนอชุดสำหรับการสั่งจริง หากข้อมูลการแพ้ที่ระบบรู้จักยืนยันแล้ว จึงเสนอปุ่ม “ดูชุดจำลองจากข้อมูลเมนู”
4. ผู้ใช้เลือก opt-in เอง แล้วกรองแท็กที่แพ้ออกจากอาหารและส่วนเพิ่มโดยคงงบ/คน/ชอบ/ไม่ชอบ ไม่เปลี่ยน evidence เป็น confirmed หรือแก้ environment ของผู้ใช้อื่น
5. การเลือกมีผลต่อมื้อและคงผ่าน rerun; รีเซ็ตกลับ deployment mode เดิม; unknown allergen ไม่เปิด opt-in
6. เลือกอาหารแล้วเพิ่มน้ำ/ขนมด้วยชื่อย่อและจำนวน เก็บตะกร้า สรุปยอดทุกครั้ง ตรวจอีกครั้งก่อนยืนยันจบ

`test_allergy_simulation_optin.py` มี 6 tests สำหรับการไม่ลด strict อัตโนมัติ การกรองทุกทางเลือก unknown allergen, reset, extras และ Streamlit click-through จนจบ เอกสารและ UI ระบุว่าชุดจำลองยังต้องให้ร้านตรวจส่วนผสม โดยเฉพาะกรณีแพ้รุนแรง

`test_thai_allergen_groups.py` ตรวจทะเบียน 10 กลุ่ม, possible/unknown โดยไม่อนุมาน absent, การคงแท็กซอส, S007 เป็น echinoderm, milk/fish ที่เพิ่มแบบ possible ตาม audit และ migration ที่ไม่ทำให้ราคาเดิมหาย เกณฑ์ฉลากบรรจุภัณฑ์ไม่ยืนยันสูตรร้าน

## รัน live LLM และขอบเขต runner

ตั้ง key ใน environment หรือ secrets อย่างปลอดภัย และกำหนด `OPENAI_MODEL` ให้ตรงโมเดลที่ต้องการประเมิน ไม่ส่ง key ผ่าน chat หรือ command arguments:

```bash
python scripts/evaluate.py --mode live --limit 3
python scripts/evaluate.py --mode live --limit 40
python scripts/live_sessions.py --output artifacts/review-round1-live-status.json
python scripts/build_report.py
```

Single-turn runner ใช้ `BudgeteerAgent()` แบบ legacy และเว้น invalid-input API cases 4 กรณี จึงรันได้สูงสุด 36 กรณีจาก corpus นี้ ส่วน multi-turn runner ใช้ `consumer_flow=True` และยืนยัน intake เมื่อจำเป็น ครอบคลุม:

- จำข้อจำกัด → เพิ่มงบ relative → ไม่กินของดิบ
- งบ 1 บาทจัดไม่ได้ → ผู้ใช้เปลี่ยนงบเป็น 300 บาท → จัดใหม่
- แพ้ปลาใน strict/unknown → ขอข้าม verify → ยังไม่เสนอชุด

Runner 3 sessions นี้ยังไม่ได้ทดสอบการกด allergy simulation opt-in แบบ live ต้องประเมินเพิ่มแยกต่างหากก่อนอ้างว่าครอบคลุมกรณีดังกล่าว การรัน `collect_evidence.py --full` ใช้ live runners ชุดเดียวกัน ไม่เพิ่ม coverage ของ opt-in เอง

เมื่อไม่มี key สคริปต์เขียน `blocked_missing_credentials`, executed=0 และ exit code 2 ไม่ใช้ fake result แทน Provider/transport error ไม่นับเป็นการจัดการข้อจำกัดสำเร็จ

## การอ่าน metrics และ trace

| ค่า | ความหมาย / ข้อจำกัด |
|---|---|
| Success rate | Outcome ตรง gold constraints; clarification ต้องถาม field ที่กำหนด |
| Safety violation among recommendations | ผลที่ขัด gold constraints ในชุดทดสอบ ไม่ใช่ความเสี่ยงแพ้อาหารที่ร้าน |
| Latency p50/p95 | เวลาชั้นที่วัด; offline ไม่มีเวลาคิดของ LLM และ benchmark เป็นเวลา algorithm |
| Model usage | รวม extraction และ tool selection ตาม metadata ของ provider; ดู `model_calls_by_phase` และ `model_events` |
| Tool selection | `route=model_selected` แยกจาก fallback `after_stall`; alternative generation/recheck อยู่ในโค้ด |
| Data mode / opt-in | `data_mode` และ `allergy_simulation_consent` ใน run report แสดงการเลือกของมื้อนั้น |
| Cost | เป็น null เมื่อ usage ไม่ครบหรือไม่ระบุราคา; ไม่ตีเป็นศูนย์ |

`agent.run_report()` เก็บ session/turn ID, model source/name, tool arguments/observations, policy decision, latency และ usage โดยมี redaction ไม่ export prompt หรือ chain-of-thought ถ้า provider ไม่รายงาน usage ครบ จะตั้ง `token_usage_complete=false` ค่าประมาณ cost ใช้ `--input-usd-per-million` / `--output-usd-per-million` ตามราคาและวันที่ที่ผู้ประเมินกำหนด และยังไม่แยก cached-token discounts

Live evaluator ตรวจผลกับ gold constraints เพื่อจับ extraction omissions แต่ยังใช้ helper บางส่วนร่วมกับแอป จึงควรเพิ่ม human review และโจทย์นอก corpus

## Objective และ benchmark ที่เทียบกันได้

ใช้ `optimization_config.py` ร่วมกับ production: `objective=budget`, `diversity=True`, spend ratio 0.8, max food items 60, repeat cap 3 งบ 300/1,000/3,000/6,000 × 3 เงื่อนไข รวม 12 กรณีและ Random 100 seeds ต่อกรณี ไม่มี allergy หรือน้ำ/ขนมใน benchmark นี้

คำนวณ diminishing score ใหม่จากจำนวนซ้ำของทุกวิธี และรายงานทั้ง share of full budget, share of food target, จำนวนเมนู/หมวด, จานตรง preference, runtime และ feasibility ตรวจ dominance ตาม lexicographic objective: หากมีชุดถึง 95% ของวงเงินอาหาร ให้ maximize score แล้ว spend; ถ้าไม่มี ให้ maximize spend แล้ว score

ผลเฉลี่ย DP ใช้งบเต็ม 76.25% / วงเงินอาหาร 95.3125% คะแนน 110.77 ขณะที่ Greedy density ใช้งบเต็ม 72.06% แต่มีคะแนน 117.44 และจำนวนหมวดเฉลี่ยสูงกว่า จึงนำเสนอ tradeoff ไม่สรุปว่า DP ชนะทุกมิติ ไม่มี objective-dominance หรือ feasibility failure ในชุดที่วัด ไม่ใช่ผลความอร่อย ความอิ่ม หรือ user study

## OPA trust boundary และข้อจำกัด

`package shiro`, policy `shiro-4.1`, input schema 2 รับ trusted catalog facts และ user constraints จาก Python แล้วเทียบ raw allergen/dietary sets เอง แม้ Python flags เป็น false ก็ตรวจ conflict ได้ แต่ Python ยังเป็นผู้สร้าง facts และ OPA ยัง deny เมื่อ `python_issues` ไม่ว่าง จึงไม่อ้างว่าทั้งสองด่านเป็นระบบอิสระโดยสมบูรณ์ OPA หาย/timeout/output ผิดจะ fail closed

ข้อมูลร้าน 42 เมนูยังไม่ยืนยันราคาและส่วนผสม ไม่มี persistence/authentication, portion model, ภาษีหรือ service charge และยังเปิด MCP subprocess ต่อ turn Tests และ policy ไม่แก้ข้อมูลต้นทางที่ไม่ครบหรือรับประกันว่าการสกัดภาษาถูกทุกข้อความ

## แนวสาธิต

เริ่มจาก consumer flow สั้นและเลือกชุด → เพิ่มน้ำ/ขนม → ยืนยันจบ จากนั้นสาธิต strict block และ explicit simulation opt-in พร้อมเตือนอย่างตรงไปตรงมา แสดง backend trace ที่ติดป้าย scripted/live ตามจริง และปิดด้วย benchmark ที่แสดงตัวหารงบทั้งสองแบบ หน้าแชตไม่มี OPA, คะแนน หรือ source table ดู findings และงานค้างใน [CODE_REVIEW.md](CODE_REVIEW.md)
