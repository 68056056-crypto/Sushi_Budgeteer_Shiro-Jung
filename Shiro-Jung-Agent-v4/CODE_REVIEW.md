# Code Review — Shiro-Jung 4.0 / package 4.2.1

เอกสารนี้รวมคำอธิบาย implementation และการตอบข้อเสนอแนะรอบ 1–2 สำหรับชุดส่งตรวจปัจจุบัน ไม่ใช่การให้คะแนนใหม่แก่โครงงาน

## เส้นทางที่ใช้ในแอปจริง

| จุดตรวจ | ไฟล์และหน้าที่ |
|---|---|
| หน้าแชต | [app.py](app.py) — Agent ต่อ `st.session_state`, สรุปยืนยัน เลือกชุด เพิ่มรายการ และรีเซ็ต |
| Agent lifecycle | [agent.py](sushi_budgeteer/agent.py) — routing, state, bounded turn, usage/report |
| รับข้อมูล | [intake.py](sushi_budgeteer/intake.py), [extraction.py](sushi_budgeteer/extraction.py) — JSON extraction, Pydantic, contextual answers, summary |
| ปฏิเสธอาหาร | [restrictions.py](sushi_budgeteer/restrictions.py), [meat_scope.py](sushi_budgeteer/meat_scope.py), [dietary.py](sushi_budgeteer/dietary.py) — hard/soft/allergy และการถามชนิดเนื้อ |
| LLM planning | [planning.py](sushi_budgeteer/planning.py) — `bind_tools`, อ่าน observations, build/verify, fallback, alternatives/rechecks |
| เพิ่มรายการ/จบมื้อ | [checkout.py](sushi_budgeteer/checkout.py), [extra_order.py](sushi_budgeteer/extra_order.py) — ชื่อย่อ+จำนวน คงอาหารเดิม รวมยอดและตรวจซ้ำ |
| MCP และ trusted snapshots | [mcp_server.py](mcp_server.py), [service.py](sushi_budgeteer/service.py) — stdio tools/resources/prompt; result_id อ้าง candidate ที่ server เก็บ |
| ฐานข้อมูล/อัลกอริทึม | [database.py](sushi_budgeteer/database.py), [optimizer.py](sushi_budgeteer/optimizer.py), [tools.py](sushi_budgeteer/tools.py) — SQLite, filters, scoring, exact DP |
| ตรวจผล | [policy.py](sushi_budgeteer/policy.py), [opa.py](sushi_budgeteer/opa.py), [recommendation.rego](policies/recommendation.rego) — คำนวณจาก catalog ใหม่และบังคับ OPA allow |
| Metadata/credentials | [telemetry.py](sushi_budgeteer/telemetry.py), [credentials.py](sushi_budgeteer/credentials.py) — safe diagnostics, redaction, single-key normalization |

`BudgeteerAgent` รวม Intake/Planning/Checkout mixins ที่ใช้ session state เดียวกัน ยังมี coupling ข้ามหน้าที่ การแยกไฟล์ไม่ได้หมายความว่าระบบแยกขาดจากกัน ไม่มี global conversation cache หรือการฝึก/fine-tune weights ของโมเดลในโครงงาน

## บทบาทโมเดลและสิทธิ์เครื่องมือ

ตั้งต้น `gpt-4o-mini`, `temperature=0`, timeout30วินาที, retries1; เปลี่ยนด้วย `OPENAI_MODEL`/Streamlit secrets ได้ ต้องอ้าง model ใน run report ของรอบนั้น การสกัดข้อมูลและการเลือก MCP tool เป็นคนละ phase

LLM เลือก tool สูงสุด10รอบ/ไม่เกิน8 callsต่อรอบ อ่านผลแล้วทำต่อ แต่ **โค้ดเป็นเจ้าของ constraints**: arguments ของ `build_set` ถูกผูกกับ state ที่ยืนยันแล้ว; `verify_set` รับ result_id ของ candidate ใน turn ปัจจุบัน โมเดลเพิ่มงบ/ลบการแพ้/ข้าม output gate เองไม่ได้ ไม่ปล่อยข้อความรายการอาหารจากโมเดลที่ยังไม่ผ่าน verify

คำตอบสั้น การเลือกชุด ชื่อย่อ+จำนวน การสร้างชุดสอง และ recheck เป็น orchestration โดยโค้ด ถ้าโมเดลไม่เลือก tool อาจมี fallback หลัง stall โดย trace แยกจาก `route=model_selected` ชัดเจน ไม่อ้างว่า LLM เลือกทุกขั้น

## ข้อเสนอแนะที่แก้แล้ว

| ประเด็นจากการตรวจ | พฤติกรรมปัจจุบันและหลักฐาน |
|---|---|
| “ไม่กินหมู” ถูกจัดเป็น dislike | กฎหลัง extraction บังคับ ไม่กิน/ไม่ทาน/งด/ห้าม → hard และลบ soft alias เดียวกันจาก state; “ไม่ค่อยชอบหมู” ยัง soft — [tests](tests/test_explicit_refusals.py) |
| “ไม่กินเนื้อ” ไม่ตัดรายการ | ถามหมู/วัว/ไก่/สัตว์บกทั้งหมดครั้งเดียว คงความหมายไม่ชอบ/ไม่กิน/แพ้ ไม่ตัดปลาเพียงเพราะเลือกสัตว์บก — [tests](tests/test_meat_scope.py) |
| สองชุดใกล้ซ้ำ | ตัด `ceil(0.30 × ชื่ออาหารไม่ซ้ำชุดแรก)` เริ่มกลุ่มคะแนนสูง ลองได้สูงสุด3กลุ่ม ตรวจสัดส่วนที่หายจริง คง extras/constraints; ทำไม่ได้แสดงชุดเดียว |
| ลูปถามน้ำ/ขนมซ้ำ | เปิดรายการและราคา รับชื่อย่อพร้อมจำนวน ตรวจตะกร้ากับอาหารเดิม แล้วให้ยืนยันรวม — [tests](tests/test_checkout_sequence.py), [ชื่อย่อ](tests/test_short_menu_names.py) |
| Agent ไฟล์ใหญ่ | แยก intake/planning/checkout ตามหน้าที่โดยรักษา API และ state ownership เดิม |
| ไม่มีหลักฐาน live | ยืนยันจริงจาก [Actions run39799552734](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39799552734): 5sessions,12/12gold,6model-selected build/verify,31responses,errors0 ที่ commit426b48a |
| ความถูกต้องของ trace | runner deep-copy state snapshots; exporter จับคู่ candidate/verify passed ด้วย result_id และใช้ build arguments ของรอบนั้น — [tests](tests/test_live_session_harness.py), [exporter](tests/test_live_trace_export.py) |

คำว่า “เงื่อนไขอื่นเหมือนเดิม” เป็นบริบทสนทนา ไม่สร้าง hard food keyword ปะปนอีกต่อไป การแก้ parser/snapshots หลัง live commit มี regression รองรับ แต่ยังไม่อ้างเป็น live rerun ใหม่

## Objective ที่อธิบายได้

คะแนนฐาน `max(0, preference + price_tier + category_weight − dislike_penalty)`; preferenceสูงสุด5, price tier3/2/1, category weight+2เมื่อไม่ใช่ปลาดิบ, dislike penalty3 จานซ้ำได้คะแนนส่วนเพิ่ม1/0.5/0.25 เป็น heuristic ไม่ใช่โภชนาการ/ความอิ่ม/ความคุ้มค่าที่ผู้ใช้รับรอง

Bounded exact DP ใช้ state `(count, cost_satang)`, immutable backtracking, GCD ลดมิติ และ state limit250,000 กำหนดใน [optimization_config.py](sushi_budgeteer/optimization_config.py): วงเงินเริ่มต้น80%, maxfood60, repeatcap3, diversitytrue, objectivebudget

หากมีชุดในช่วง95–100%ของวงเงินอาหาร เลือกคะแนนลดซ้ำสูงสุดแล้วใช้ยอดเงินเป็น tie break ถ้าไม่มีชุดในช่วงนั้น เลือกยอดสูงสุดก่อนคะแนน จึง **ไม่ได้อ้างว่า DP ชนะ Greedy ทุกตัวชี้วัด** ผลเฉลี่ย DP score110.77 / ใช้งบเต็ม76.25% เทียบ Greedy density score117.44 / ใช้งบเต็ม72.06% ขอบเขตและค่าจริงอยู่ใน [EVALUATION.md](EVALUATION.md)

## Trust boundary และข้อมูลแพ้อาหาร

Python สร้าง trusted facts จาก SQLite; Rego policy `shiro-4.2` schema2 เทียบ raw allergen/dietary sets แม้ Python flagsเป็นfalse แต่ OPA ยังใช้ facts จาก Pythonและdenyเมื่อ python_issues ไม่ว่าง จึงไม่ได้เป็นระบบอิสระจากกันโดยสมบูรณ์ OPA หาย/timeout/outputผิด → fail closed

`strict` รับผู้แพ้เฉพาะรายการที่ allergen_status confirmed และไม่ชนแท็ก; unknown/team_reviewed ไม่ปลด strict การดูชุดจำลองต้อง opt-in เองและยังมีคำเตือน ไม่ใช้ชื่อเมนูแทนหลักฐานสูตรหรือรับประกันปนเปื้อนข้าม

## ข้อจำกัดที่ยังเหลือ

- ข้อมูลราคา/ส่วนผสม42รายการยัง unverified/unknown; ไม่มีหลักฐานร้านใหม่ในชุดส่งนี้
- Live ผ่านเฉพาะ5sessions/12goldที่ระบุ ไม่ใช่ human preference study หรือคุณภาพทุก prompt
- ไม่มี durable conversation persistence/account system; SQLite เก็บ catalog ไม่ใช่ความจำบทสนทนาหลัง refresh
- MCP เปิด subprocess ต่อ planning turn และมี rechecks หลายรอบ ยังไม่ได้พิสูจน์ latency improvement เชิงควบคุม
- ไม่คำนวณ portion/ความอิ่ม/ภาษี/service charge และไม่ส่งออเดอร์จริง

## การจัดชุด GitHub สำหรับส่งตรวจ

เก็บ entrypoint, CSV, dependencies, runtime package, policy และ OPA executable ที่ Cloud ใช้ไว้ รวมผลเก่าให้เหลือ [หลักฐาน7ไฟล์](EVALUATION.md#หลักฐานปัจจุบัน) และเอกสารหลัก4ไฟล์ ลบ RAG/LLM terminal/CLI ทดลองและ packager เก่าที่ไม่ได้อยู่ในเส้นทางแอป ประวัติก่อนจัดชุดอยู่ที่ commit3af6b28; ตำแหน่ง Streamlit เดิมคือ `Shiro-Jung-Agent-v4/app.py`
