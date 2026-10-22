# Evaluation — Shiro-Jung 4.0 / package 4.3.0

เอกสารนี้แยก **offline regression / gold tools / benchmark / live LLM** ไม่รวมจำนวนหรืออ้างผลแทนกัน วันที่และ revision ดูจาก JSON ของแต่ละการรัน

## ผลที่ยืนยันได้

| ชั้นการประเมิน | ผล | ขอบเขต |
|---|---|---|
| Regression/integration | 182ผ่าน, failures0/errors0/skips0 | scripted model + real MCP subprocess, SQLite, OPA และ Streamlit AppTest |
| Rego | 25/25 | กฎ allow/deny รวม raw-tag conflicts และ Python flagsfalse |
| Smoke | strict61/61 และ simulation61/61 | ตรวจทั้งสองโหมด ไม่ลด strict เพื่อให้ผ่าน |
| Offline gold | 40/40 | ใช้ tools โดยไม่เรียก LLM; ไม่วัดคุณภาพ extraction/provider |
| Production benchmark | 12สถานการณ์, Random1,200รอบ | objective/configเดียวกับอาหารเริ่มต้นบนเว็บ |
| Live consumer sessions | gold12/12ใน5sessions | แนะนำ6/block4/clarify2;18actualchatturnsรวม confirmations |
| Live model selection | 6recommendations | มี route=model_selected ของ build_set และ verify_set passed โดย result_idตรงกัน |
| Live provider usage | 31responses, errors0 | input113,459 + output2,548 =116,007tokens; ไม่ตีราคาเป็นเงินโดยไม่มีราคาที่ใช้อ้างอิง |

ผล live จาก [GitHub Actions run39799552734](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39799552734) ที่ **source commit426b48a** ใช้โมเดลที่ตั้งค่า **gpt-4o-mini** รายงานสร้าง22ต.ค.2569เวลา21:53น. (Asia/Bangkok) ตรวจจาก artifact ที่ผู้ใช้ส่ง ไม่ใช่การเรียก API ใหม่ในเครื่องจัดชุด

## หลักฐานปัจจุบัน

| ไฟล์ | สิ่งที่อาจารย์ตรวจได้ |
|---|---|
| [checks.json](artifacts/checks.json) | validation counts, Python/platform/release, Rego25กรณี และ smoke logsทั้งสองโหมด รวมเป็นไฟล์เดียว |
| [offline-evaluation.json](artifacts/offline-evaluation.json) | gold40กรณี, outcome/expected, policy, tools/latency และ catalog revision |
| [benchmark.json](artifacts/benchmark.json) | config, DP/greedy/random รายสถานการณ์, seeds และ summary |
| [catalog-audit.json](artifacts/catalog-audit.json) | provenance42เมนูและรายการหลักฐานที่ยังขาด ไม่มีการตั้งconfirmedอัตโนมัติ |
| [live-sessions.json](artifacts/live-sessions.json) | JSON live ต้นฉบับจาก Actions เก็บ byte-for-byte |
| [live-trace.md](artifacts/live-trace.md) | trace จริงหนึ่ง session ที่จับคู่ candidate/verification; historical constraints จาก build arguments ของรอบเดียวกัน |
| [evidence-summary.json](artifacts/evidence-summary.json) | ผล live ที่ตรวจนับซ้ำ, source commit/run URL, SHA256 และขอบเขตการย้าย/รวมหลักฐาน |

`checks.json` มี live_llm_api_tested=false เพราะคำสั่งตรวจนั้นเป็น offline ส่วนหลักฐาน providerจริงอยู่ใน live-sessions.json ซึ่ง live_llm_tested=true เป็นคนละชั้นการประเมิน ผลย้อนหลัง/ไฟล์ซ้ำเก็บใน Git history แทนการแสดงหลายรุ่นปะปนในชุดส่ง

## ตรวจซ้ำแบบ offline

จากโฟลเดอร์ `Shiro-Jung-Agent-v4` หลังติดตั้ง requirements:

```bash
python scripts/collect_evidence.py
```

คำสั่งเดียวตรวจ OPA → regression/smoke/Rego → offline40 → benchmark → catalog audit → สร้าง `artifacts/report.html` เพื่อเปิดตรวจใน browser ไม่เรียก LLM API และไม่แก้หลักฐาน live เดิม ไม่ import ทับ catalogที่มีอยู่

คำสั่งแยกสำหรับตรวจเฉพาะชั้น:

```bash
python scripts/run_checks.py
python scripts/evaluate.py
python scripts/benchmark.py
python scripts/catalog_audit.py
python mcp_client_demo.py
python scripts/build_report.py
```

ไฟล์ report.html เป็นผลสร้างในเครื่อง ไม่ต้องเก็บบน GitHub ส่วน CSV import เป็น replace operation จึงควรสำรอง SQLite หากทีมเพิ่มหลักฐาน/ราคาเองก่อนใช้ `python -m sushi_budgeteer.database import`

## Action plan: ตรวจงบขั้นต่ำตั้งแต่ intake

ใช้เกณฑ์งบเต็ม **100บาทต่อคน**: ต่ำกว่าเกณฑ์เตือนและรอแก้ข้อมูลก่อนยืนยันหรือเปิด planning/MCP เท่ากับเกณฑ์ถือว่าผ่านด่าน intake เช่น300บาท/3คน แต่ยังต้องผ่านการแพ้/ข้อห้าม/งบจริงของชุดในขั้นถัดไป ไม่ตีความว่าเกณฑ์นี้รับประกันความอิ่มหรือความเป็นไปได้ทุกเมนู

`test_intake_budget.py` เพิ่ม7เคส: 50/3เตือนพร้อมคงข้อจำกัด, กดยืนยัน/เรียกplanningข้ามไม่ได้, ตอบเฉพาะงบใหม่, ขอบเขต299.99/300/300.01สำหรับ3คนและเปลี่ยนจำนวนคน, รับข้อมูลทีละส่วน/ลดงบหลังเคยจัดชุด, ปุ่มUIไม่เปิดจนงบผ่าน และ scripted runnerผ่านการเตือน→แก้งบ→จัดชุด โดยไม่อ้างเป็น live

corpusปัจจุบัน5sessions/12goldมี `budget_revision` 1กรณี ซึ่งต้องมี intake_checkที่ถูกต้อง ไม่มีcandidate/confirmation/MCPcalls และรักษาคน/ข้อห้ามไว้ ส่วน artifact liveต้นฉบับยังคงเป็น source426b48aก่อนเพิ่มกฎนี้และไม่ถูกแก้ให้ดูเหมือนทดสอบกฎใหม่แล้ว

## รัน Live LLM ใหม่

[workflow](../.github/workflows/live-llm-evaluation.yml) เป็น manual dispatch ใช้ Python3.12, requirements.lock, OPA1.0.1 และ `gpt-4o-mini` ไม่มีการเรียก API แบบเสียเงินทุกครั้งที่ push

1. ตั้ง GitHub Actions Secret ชื่อ `OPENAI_API_KEY` โดยใส่เฉพาะคีย์หนึ่งค่า
2. Actions → Live LLM evaluation → Run workflow → main
3. ต้องได้ success_rate1.0, live_llm_tested=true และ model_selected_recommendations>0 จึงผ่าน job
4. ดาวน์โหลด artifact อายุ90วัน รวม JSON และ live-trace.md แม้ gold checksล้มเหลวจะยังอัปโหลดผล; ไม่ push key หรือผลใหม่กลับ repoอัตโนมัติ

รัน local เทียบเท่าเมื่อกำหนด key ใน environment อย่างปลอดภัย:

```bash
python scripts/live_sessions.py --scenarios evaluation/sessions.json --output artifacts/generated/live-sessions.json --require-model-selected
python scripts/summarize_live.py --input artifacts/generated/live-sessions.json
python scripts/export_live_trace.py --input artifacts/generated/live-sessions.json --output artifacts/generated/live-trace.md
python scripts/build_report.py --live-report artifacts/generated/live-sessions.json
```

`evaluation/sessions.json` มี5sessions/12goldturns: จำมื้อและเพิ่มงบ/ห้ามดิบ/ไม่กินหมู, งบทำไม่ได้แล้วผู้ใช้แก้, ขอข้าม verifyขณะแพ้ปลา, เลือกชนิดเนื้อสัตว์บก, แพ้เนื้อ→strictblock→explicit simulation opt-in corpusเดิมมาจาก round2_sessions.json ของ live commit426b48a; รอบปัจจุบันเปลี่ยนกรณีงบ1บาทเป็น50บาท/3คนและคาดหวัง budget_revision ก่อน planning ผล liveเดิมจึงไม่ใช่ผลทดสอบกฎใหม่นี้

## วิธีอ่านผลและข้อจำกัด trace

- `executed_turns` นับ actual chat attempts รวม confirmations ไม่ใช่จำนวน API responses; `model_calls` นับ responsesที่ได้รับจริง
- `model_selected_recommendations` นับเฉพาะ successful live recommendation ที่ LLMเลือก build/verifyเอง; fallback/alternative generation/recheck โดยโค้ดไม่นับแทน
- Provider errors/transport errors ไม่ถือเป็น successful safety block ค่า keyมีรูปแบบถูกต้องไม่รับรองสิทธิ์หรือเครดิต API
- รายงานเก็บ safe diagnostics/redaction ไม่เก็บ API key, raw prompt หรือ chain-of-thought
- การวัด latency ของ offline/DP ไม่ใช่เวลาตอบแชตของ LLM และ tokensไม่ใช่ค่าใช้จ่ายจนกว่าจะกำหนดราคาที่อ้างอิง

**ข้อจำกัด artifact เดิม:** ลิสต์ใน `turn.state` แชร์ references จึงอาจมีข้อมูลจากรอบหลังเติมเข้าไป runnerปัจจุบัน deep-copyแล้ว; traceนำเสนออ่าน constraintsจาก `build_set.arguments` ของรอบเดียวกัน เก็บ JSONliveต้นฉบับไว้และไม่แก้ตัวเลขให้ผ่าน ไฟล์ traceต้นฉบับที่มีปัญหายังตรวจได้ใน [commit3af6b28](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/blob/3af6b28/Shiro-Jung-Agent-v4/artifacts/live-confirmed-39799552734/original-live-trace.md)

Live success เป็นผล runnerที่ใช้ validation helpersร่วมกับแอป ไม่มี raw final-menu payloadครบสำหรับ independent replay และยังไม่มี human preference study การแก้ snapshot/exporter/parserภายหลังผ่าน offline regression **ไม่ใช่ live rerun ใหม่** ผล100% จำกัดที่ corpus/commitนี้ ไม่รับรองทุกpromptหรือสูตรร้าน

## Regression จาก review ล่าสุด

`tests/test_requested_meals.py` มี10เคส: required coverage เทียบ exhaustive optimum, ขอ/บังคับเมนูและ alternative, verify ปฏิเสธเมนูที่ขาด, ความชอบทูน่าขัดข้อห้ามของดิบ, min>max เก็บข้อมูลที่ถูกต้อง, งบ0/เบียร์/ราคาไม่ล้างชุด, explicit cap เน้นความหลากหลาย, session round-trip/แยกผู้ใช้/หมดอายุ/ไม่บันทึก key, snapshot เปลี่ยนต้องจัดใหม่, Streamlit refresh+ปุ่มราคา และ real MCP required build→verify (บางเคสตรวจหลายพฤติกรรมร่วมกัน)

Live ที่แนบเป็นผล source426b48a ก่อนเปลี่ยน scoring/required menu/explicit-cap objective และ session persistence ชุดใหม่ จึงใช้ยืนยันได้เฉพาะความสามารถและ corpus ณ commit นั้น ไม่อ้างว่าตัวเลข live12/12 เป็นผลรัน package4.3.0

## Objective และ benchmark

Benchmark นี้วัดกรณีไม่มี explicit plate cap และไม่มี required menu เท่านั้น; กรณีใหม่มี regression แยก ไม่ใช้ตัวเลขนี้รับรอง optimality ของทุกเงื่อนไข

Configร่วม: objectivebudget, diversitytrue, spend_ratio0.8, maxfood60, repeatcap3 DPเรียงคะแนนก่อนในช่วง95–100%ของวงเงินอาหาร; หากทำช่วงนั้นไม่ได้เรียงยอดเงินก่อนคะแนน ทั้งสาม baselineใช้ข้อจำกัดเดียวกัน ไม่ใช้ rawscoreเพียงอย่างเดียวตัดสินobjective dominance

| วิธี | ใช้งบเต็มเฉลี่ย | ใช้วงเงินอาหารเฉลี่ย | คะแนนลดซ้ำเฉลี่ย |
|---|---:|---:|---:|
| DP | 76.25% | 95.3125% | 123.44 |
| Greedy density | 72.11% | 90.14% | 130.77 |

ไม่มี feasibility/objective-dominance failureในชุดbenchmarkนี้ แต่ Greedy densityได้คะแนนและความหลากหลายเฉลี่ยสูงกว่า จึงไม่อ้างว่า DPดีที่สุดทุกตัวชี้วัด 76.25%ของงบเต็มมีตัวหารต่างจาก95.3125%ของวงเงินอาหาร และไม่รวม extrasที่เพิ่มภายหลัง ส่วนที่สำรองเป็นนโยบายผลิตภัณฑ์ ไม่ใช่ผลวิจัยความอิ่มหรือความพึงพอใจ

## การตรวจแอปหลังจัดชุด GitHub

คง entrypoint `Shiro-Jung-Agent-v4/app.py`, CSV, requirements และ OPAที่แอปใช้จริง ตรวจ Streamlit AppTest/consumer flows กับ MCP subprocessจริงใน regression และตรวจการเปิด serverในเครื่อง ไม่มีการแก้ค่า Secrets ของ deploymentจากการจัดโครงสร้าง repository การเปิด URLปลายทางยังต้องตรวจจาก browserที่เข้าถึง Streamlit Cloudได้
