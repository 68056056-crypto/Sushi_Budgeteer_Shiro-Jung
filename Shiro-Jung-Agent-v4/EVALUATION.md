# Evaluation — Shiro-Jung 4.2.1

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

## เกณฑ์เพิ่มหลังข้อเสนอแนะจากเว็บจริง

เพิ่ม regression 17 เคส: hard refusal ที่โมเดลจัดผิด/หลายข้อห้าม/alias ใน state เดิม/strict→opt-in จริงผ่าน MCP, soft dislike, ตัวเลือกต่าง ≥30%, team-reviewed import/migration/strict gate และ live-trace exporter ที่ไม่รับ scripted/fallback

สัดส่วนความต่าง = จำนวน **ชื่อเมนูอาหารไม่ซ้ำของชุดแรกที่ไม่อยู่ชุดสอง** ÷ จำนวนชื่อเมนูอาหารไม่ซ้ำในชุดแรก ต้อง ≥0.30; ไม่ใช่ Jaccard และไม่ใช่จำนวนจานรวมหรือความชอบเชิงผู้ใช้ เครื่องดื่ม/ของหวานไม่นับในตัวหาร ใช้ fixed allocation เดิม ไม่มีชุดที่ต่างเพียงพอจะเสนอชุดเดียว ผลนี้ไม่ใช่ user preference study

หลักฐาน live จาก Actions ผ่านแล้วตามตารางด้านบน เครื่องนี้ไม่เรียก API ซ้ำ State ยังอยู่ใน Streamlit session; SQLite เก็บ catalog ไม่ใช่บทสนทนาที่กู้คืนหลัง refresh/session ใหม่

### รันบน GitHub Actions

1. เพิ่ม `OPENAI_API_KEY` ใน repository Settings → Secrets and variables → Actions ด้วยบัญชีที่มีสิทธิ์
2. Actions → **Live LLM evaluation** → Run workflow บน main ใช้ [workflow](../.github/workflows/live-llm-evaluation.yml)
3. ตรวจ success rate 1.0, live true, model-selected recommendations >0; ตรวจ JSON ว่ามี successful `route=model_selected` สำหรับ build_set และ verify_set ใน live run เดียวกัน ไม่ใช้ fallback แทน
4. ดาวน์โหลด artifact อายุ 90 วันรวม `live-sessions.json` และ `live-trace.md` นำ trace จริงหนึ่ง session ไปแทนหน้าสถานะรอหลักฐานในสไลด์ ไฟล์ artifact ไม่ถูก push กลับ repo

คำสั่ง local เทียบเท่า (ตั้ง key ผ่าน environment อย่างปลอดภัยก่อน):

```bash
python scripts/live_sessions.py --scenarios evaluation/round2_sessions.json --output artifacts/live-actions/live-sessions.json --require-model-selected
python scripts/summarize_live.py --input artifacts/live-actions/live-sessions.json
python scripts/export_live_trace.py --input artifacts/live-actions/live-sessions.json --output artifacts/live-actions/live-trace.md
```

`--require-model-selected` ทำให้ runner ล้มเหลวแม้ทุก gold turn ผ่านถ้าไม่มี successful real-provider model-selected recommendation และไม่เปลี่ยน scripted output เป็น live การสรุป/อัปโหลด artifacts ใช้ `if: always()` เพื่อเก็บหลักฐานตอน failure

อ้างอิง implementation รอบแก้ไข 2 และ artifacts ล่าสุดที่ระบุด้านล่าง ตรวจความสอดคล้องเอกสารวันที่ 22 ตุลาคม 2569 รัน regression, offline evaluation และ benchmark ใหม่หลังแก้โค้ด โดยไม่สร้างผล live แทนการเรียก provider

## โมเดลและวิธีทดสอบ

โมเดลเริ่มต้นคือ OpenAI `gpt-4o-mini` ผ่าน `ChatOpenAI`, `temperature=0`, timeout 30 วินาที, `max_retries=1` เปลี่ยนโมเดลด้วย `OPENAI_MODEL` หรือการตั้งค่า Streamlit การระบุชื่อ default ไม่ยืนยันว่าการ deploy ใช้ค่านั้น ให้ตรวจ `model` และ `model_source` ใน run report ของการเรียกจริง

| ชั้นการประเมิน | สิ่งที่รัน / ผลล่าสุด | ขอบเขต |
|---|---|---|
| Regression / integration | 165 tests ผ่าน | scripted model + real MCP subprocess, SQLite, OPA และ Streamlit AppTest |
| OPA / Rego | 25/25 | ตรวจกฎแยก รวม raw-tag conflicts และ fail closed |
| Smoke | strict 61/61, simulation 61/61 | โหมด strict ต้องปฏิเสธการแพ้เมื่อ evidence ไม่พอ ไม่ลดโหมดเพื่อให้ผ่าน |
| Offline gold | 40/40 | ไม่มีโมเดล; ทดสอบ tools/constraints บน seed catalog |
| Production benchmark | 12 กรณี, Random 1,200 ครั้ง | objective/config เดียวกับอาหารเริ่มต้นบนเว็บ |
| Live single-turn | ยังไม่มีผลรัน | runner ใช้ legacy Agent readiness ไม่ใช่ consumer opt-in flow |
| Live consumer sessions | `completed`, 12/12 gold, 18 actual turns, 31 model responses, 6 model-selected recommendations | `artifacts/live-confirmed-39799552734/live-sessions.json`, source 426b48a |
| Consumer allergy opt-in | 6 regression tests และ live session land_meat_allergy_explicit_optin ผ่าน | แยก strict block / consent / simulation; ไม่ใช่ร้านยืนยัน |

ผล regression รอบแก้ไข 2 ดูวันเวลา `checked_at` จาก JSON (UTC; เวลาไทย UTC+7) อยู่ใน `artifacts/review-live-confirmed-checks/validation-report.json` จำนวน tests และผล scripted ไม่รับรองคุณภาพภาษาไทยของ live model หรือความปลอดภัยของสูตรร้าน

## แหล่งหลักฐานที่ใช้

| ไฟล์ | หน้าที่ |
|---|---|
| `artifacts/review-live-confirmed-checks/validation-report.json` | จำนวน tests, failures/errors, Python/platform, smoke modes และสถานะ live |
| `artifacts/review-live-confirmed-checks/opa-tests.json` | ผล Rego 25 กรณี |
| `artifacts/review-live-confirmed-checks/smoke-strict.log`, `smoke-simulation.log` | ผล smoke รายโหมด |
| `artifacts/review-round2-followup/offline-evaluation.json` | 40 gold outcomes, catalog revision และ offline metrics |
| `artifacts/review-round2-followup/benchmark-production.json` | config, ผลทุกวิธี, Random seeds และตัวชี้วัดรายกรณี |
| `artifacts/review-round2-followup/scripted-consumer-trace.json` | หลักฐานต่อวงจร consumer planning/replan ด้วย scripted model; ไม่ใช่ live |
| `artifacts/live-confirmed-39799552734/live-sessions.json` | ผล live จริงที่ผู้ใช้ส่งจาก Actions; ไฟล์ live-status เดิมเป็นประวัติก่อนมี credentials |
| `artifacts/live-evaluation.json` | สถานะ/ผลของ single-turn live runner เมื่อรันจริง |
| `artifacts/review-round2-followup-report.html` | รายงานที่สร้างจาก JSON ข้างต้น; ไม่รันทดสอบเอง |

`artifacts/validation-report.json`, `opa-tests.json`, `offline-evaluation.json`, `live-sessions.json` และ `benchmark.json` ชื่อเดิมเป็น snapshot รุ่นก่อน อย่านำตัวเลขมารวมกับผลล่าสุดโดยไม่ตรวจวันที่ ขอบเขต และ revision หน้าแชตไม่แสดงตาราง technical evidence หรือปุ่มดาวน์โหลด trace; ใช้ backend `agent.run_report()` และสคริปต์รายงาน

## ทำซ้ำแบบ offline

รันจาก `Shiro-Jung-Agent-v4` หลังติดตั้ง dependencies และ OPA โดยไม่ต้องมี API key:

```bash
python scripts/install_opa.py
python scripts/run_checks.py --output-dir artifacts/review-live-confirmed-checks
python scripts/evaluate.py --mode offline --output artifacts/review-round2-followup/offline-evaluation.json
python scripts/benchmark.py --output artifacts/review-round2-followup/benchmark-production.json
python scripts/build_report.py
```

เปิด `artifacts/review-round2-followup-report.html` ใน browser เพื่อดูผลและเลือก benchmark รายสถานการณ์ การสร้าง HTML อ่าน artifacts ที่มีอยู่ ไม่อัปเดตผลทดสอบหรือเติมผลที่ยังไม่มี

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
python scripts/live_sessions.py --scenarios evaluation/round2_sessions.json --output artifacts/review-round2-followup/live-status.json
python scripts/build_report.py
```

Single-turn runner ใช้ `BudgeteerAgent()` แบบ legacy และเว้น invalid-input API cases 4 กรณี จึงรันได้สูงสุด 36 กรณีจาก corpus นี้ ส่วน multi-turn runner ใช้ `consumer_flow=True` และยืนยัน intake เมื่อจำเป็น ครอบคลุม:

- จำข้อจำกัด → เพิ่มงบ relative → ไม่กินของดิบ
- งบ 1 บาทจัดไม่ได้ → ผู้ใช้เปลี่ยนงบเป็น 300 บาท → จัดใหม่
- แพ้ปลาใน strict/unknown → ขอข้าม verify → ยังไม่เสนอชุด

Corpus รอบ 2 เพิ่มอีก 2 sessions: “ไม่กินเนื้อ” → เลือกสัตว์บกทั้งหมด และ “แพ้เนื้อ” → เลือกไก่ → strict block → explicit simulation opt-in รวม 5 sessions / 12 gold turns สคริปต์ยืนยัน intake อัตโนมัติเมื่อพร้อม จึงอาจมี model turns มากกว่า gold turns ตรวจ expected mode และ consent เพิ่มเพื่อจับการลด strict โดยไม่ได้เลือก

`--scenarios` ค่าเริ่มต้นยังเป็น `evaluation/sessions.json` รุ่นก่อน 3 sessions; ผล live ที่ยืนยันแล้วระบุ `evaluation/round2_sessions.json` 5 sessions/12 gold turns อย่างชัดเจน ส่วน `test_live_session_harness.py` ใช้ scripted Agent + real MCP และไม่นับเป็น live แม้ได้ success_rate=1

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

`package shiro`, policy `shiro-4.2`, input schema 2 รับ trusted catalog facts และ user constraints จาก Python แล้วเทียบ raw allergen/dietary sets เอง แม้ Python flags เป็น false ก็ตรวจ conflict ได้ แต่ Python ยังเป็นผู้สร้าง facts และ OPA ยัง deny เมื่อ `python_issues` ไม่ว่าง จึงไม่อ้างว่าทั้งสองด่านเป็นระบบอิสระโดยสมบูรณ์ OPA หาย/timeout/output ผิดจะ fail closed

ข้อมูลร้าน 42 เมนูยังไม่ยืนยันราคาและส่วนผสม ไม่มี persistence/authentication, portion model, ภาษีหรือ service charge และยังเปิด MCP subprocess ต่อ turn Tests และ policy ไม่แก้ข้อมูลต้นทางที่ไม่ครบหรือรับประกันว่าการสกัดภาษาถูกทุกข้อความ

## แนวสาธิต

เริ่มจาก consumer flow สั้นและเลือกชุด → เพิ่มน้ำ/ขนม → ยืนยันจบ จากนั้นสาธิต strict block และ explicit simulation opt-in พร้อมเตือนอย่างตรงไปตรงมา แสดง backend trace ที่ติดป้าย scripted/live ตามจริง และปิดด้วย benchmark ที่แสดงตัวหารงบทั้งสองแบบ หน้าแชตไม่มี OPA, คะแนน หรือ source table ดู findings และงานค้างใน [CODE_REVIEW.md](CODE_REVIEW.md)


## ขอบเขตข้อประเมินรอบ 2

`test_round2_meat_scope.py` เพิ่ม 10 กรณีสำหรับคำกว้าง/คำเฉพาะ/ปฏิเสธการแพ้, soft dislike, hard exclusion, medical meat filtering และ raw Rego conflict, รักษาการแพ้ปลาเดิม, เปลี่ยนเงื่อนไขหลังเลือกอาหาร และ UI ที่ไม่ถามงบใหม่ `test_live_session_harness.py` เพิ่ม 2 กรณี offline สำหรับสถานะไม่มี credentials และการรัน scenario meat/opt-in โดยไม่อ้าง scripted เป็น live

Audit ข้อมูลจาก `scripts/catalog_audit.py` พบ allergen unknown42/42 และราคาunverified42/42 พร้อมสร้าง checklist 42 เมนูสำหรับผู้ตรวจจริง ไม่ใช่การรับรองสถานะ ข้อประเมินที่อ้าง offline40ว่าเป็น scripted ให้แยกตามโค้ด: gold40เรียกtoolsโดยไม่มี LLM ขณะที่ regressionของAgent/harnessใช้scripted model ทั้งสองประเภทไม่ใช่หลักฐาน live
