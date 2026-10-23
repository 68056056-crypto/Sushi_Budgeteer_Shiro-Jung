# Code Review — Shiro-Jung 4.0 / package 4.4.0

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
| งบต่ำมากเทียบจำนวนคน | intakeบังคับงบรวม ≥100บาท×จำนวนคน ก่อนแสดงปุ่มยืนยัน/เรียกplanning; 50บาท3คนเตือน300บาท คงมื้อเดิม — [tests](tests/test_intake_budget.py) |
| “ไม่กินหมู” ถูกจัดเป็น dislike | กฎหลัง extraction บังคับ ไม่กิน/ไม่ทาน/งด/ห้าม → hard และลบ soft alias เดียวกันจาก state; “ไม่ค่อยชอบหมู” ยัง soft — [tests](tests/test_explicit_refusals.py) |
| “ไม่กินเนื้อ” ไม่ตัดรายการ | ถามหมู/วัว/ไก่/สัตว์บกทั้งหมดครั้งเดียว คงความหมายไม่ชอบ/ไม่กิน/แพ้ ไม่ตัดปลาเพียงเพราะเลือกสัตว์บก — [tests](tests/test_meat_scope.py) |
| สองชุดใกล้ซ้ำ | ตัด `ceil(0.30 × ชื่ออาหารไม่ซ้ำชุดแรก)` เริ่มกลุ่มคะแนนสูง ลองได้สูงสุด3กลุ่ม ตรวจสัดส่วนที่หายจริง คง extras/constraints; ทำไม่ได้แสดงชุดเดียว |
| ลูปถามน้ำ/ขนมซ้ำ | เปิดรายการและราคา รับชื่อย่อพร้อมจำนวน ตรวจตะกร้ากับอาหารเดิม แล้วให้ยืนยันรวม — [tests](tests/test_checkout_sequence.py), [ชื่อย่อ](tests/test_short_menu_names.py) |
| Agent ไฟล์ใหญ่ | แยก intake/planning/checkout ตามหน้าที่โดยรักษา API และ state ownership เดิม |
| ไม่มีหลักฐาน live | ยืนยันจริงจาก [Actions run39799552734](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39799552734): 5sessions,12/12gold,6model-selected build/verify,31responses,errors0 ที่ commit426b48a |
| ความถูกต้องของ trace | runner deep-copy state snapshots; exporter จับคู่ candidate/verify passed ด้วย result_id และใช้ build arguments ของรอบนั้น — [tests](tests/test_live_session_harness.py), [exporter](tests/test_live_trace_export.py) |

คำว่า “เงื่อนไขอื่นเหมือนเดิม” เป็นบริบทสนทนา ไม่สร้าง hard food keyword ปะปนอีกต่อไป การแก้ parser/snapshots หลัง live commit มี regression รองรับ แต่ยังไม่อ้างเป็น live rerun ใหม่

## จุดตรวจเพิ่มเติม 4.4.0

`menu_matching.py` แยก exact identity ออกจาก display-only suggestions; DP required coverage และ validator ใช้ชื่อ/keyword เต็มจาก catalog อ้าง item_id อีกครั้ง ถอน matcher edit-distance/substring เดิมที่ไม่ใช้งานออกจาก optimizer แล้ว คะแนน soft/ONLY ใช้ alias เต็มหรือกลุ่ม dietary ที่ระบุชัดเจน ไม่ fuzzy เมนูแทนผู้ใช้

`extra_order.py` รวม registry ชื่อย่อไว้จุดเดียว ใช้ทั้ง parser, ตรวจ unknown และ resolver ใน tools; ชื่อที่ไม่พบไม่ถูกใส่บางส่วน งบที่ extraction ให้≤0 เข้า structured intake validation ก่อน update/planning เก็บข้อมูลส่วนที่ถูกต้องและถามใหม่ โดย contextual budget รองรับเลขมีเครื่องหมาย/ทศนิยม

`tests/test_exact_intake.py` เพิ่ม11เคส รวมโอโทโร่≠เนกิโทโร่, ชื่อผิดต้องยืนยัน, ราคาสูงต้องถาม, ศูนย์/ติดลบหลายรูปแบบ, unknown เครื่องดื่มและขนมทุกชื่อ และทดสอบ runner ใหม่ด้วย scripted model โดยไม่เรียกว่า live ใหม่

Workflow ใช้ manual dispatch หรือ tag-prefix `live-eval-*` โดยไม่เปิดpaidLLMให้push branchทั่วไป; ใช้ current corpus6sessions/14gold และ runner บันทึก package_version/scenario_sha256 พร้อม source_commit; gold ตรวจrequired item IDs จริง การเก็บหลักฐานร้านไม่อยู่ในขอบเขตรอบนี้ และไม่มีการเปลี่ยน unknown เป็น confirmed

## Review รอบล่าสุด — package 4.4.0

| ปัญหา | การแก้และจุดตรวจ |
|---|---|
| ขอเมนูแล้วไม่อยู่ในชุด | `intake.py` แยก `required_keywords` จาก ONLY filter; `state.py` จำคำขอ; MCP `build_set` ส่งต่อ; DP coverage bitmask บังคับครบทุกคำ (สูงสุด 8); `policy.py` ตรวจซ้ำจาก item_id ใน catalog |
| ความชอบขัดข้อห้าม | `tools.py` เทียบเมนูต้นฉบับกับหลังกรองและส่ง `preference_warnings`; `presentation.py` แจ้งผู้ใช้; required menu ที่ขัด/ไม่มี/งบไม่พอไม่ผ่าน validation |
| min > max ทำข้อมูลหาย | `agent.py` บันทึกเฉพาะฟิลด์ที่ถูกต้องก่อนถามแก้จำนวนจาน ไม่แก้ตัวเลขให้ผ่านเอง |
| จานน้อยแต่เมนูแพงซ้ำ | `max_items_explicit=True` → score-first, repeat cap2; preference6/คำสูงสุด12; ไม่ปรับ allergy/hard exclusions และไม่เพิ่มของหวานเอง |
| ปุ่มเลือกชุดหายเมื่อถามราคา | read-only catalog lookup ก่อน reset ตัวเลือก/checkout; เบียร์นอก catalog มีข้อความตรงตัว |
| รีเฟรชแล้วข้อมูลหาย | `persistence.py` JSON allowlist + SQLite + random256-bit session token, TTL24ชม.; ไม่ serialize API key/client/trace; ตรวจ catalog/policy อีกครั้งก่อนใช้ชุดเก่า |

ทดสอบทั้ง real MCP build→verify และ Streamlit AppTest: ถามราคาแล้วปุ่มยังอยู่, เปิด session เดิมในหน้าใหม่คืนตัวเลือกและเลือกได้ หลักฐานอยู่ `tests/test_requested_meals.py` รวม10เคส ไม่ใช่ live LLM run ใหม่ ข้อมูลร้านยังไม่ตั้ง confirmed โดยไม่มีหลักฐาน

## Objective ที่อธิบายได้

คะแนนฐาน `max(0, preference + price_tier + category_weight − dislike_penalty)`; preference 6 ต่อคำที่ตรง สูงสุด12 (มากกว่า price+category สูงสุด5), price tier3/2/1, category weight+2เมื่อไม่ใช่ปลาดิบ, dislike penalty3 จานซ้ำได้คะแนนส่วนเพิ่ม1/0.5/0.25 เป็น heuristic ไม่ใช่โภชนาการ/ความอิ่ม/ความคุ้มค่าที่ผู้ใช้รับรอง

Bounded exact DP ใช้ state `(count, cost_satang, required_coverage_mask)`, immutable backtracking, GCD ลดมิติ และ state limit250,000 กำหนดใน [optimization_config.py](sushi_budgeteer/optimization_config.py): วงเงินเริ่มต้น80%, maxfood60, repeatcap3, diversitytrue, objectivebudget; หากจำกัดจานเองใช้ objective score และ repeatcap2

กรณีไม่ได้จำกัดจำนวนจาน: หากมีชุดในช่วง95–100%ของวงเงินอาหาร เลือกคะแนนลดซ้ำสูงสุดแล้วใช้ยอดเงินเป็น tie break ถ้าไม่มีชุดในช่วงนั้น เลือกยอดสูงสุดก่อนคะแนน จึง **ไม่ได้อ้างว่า DP ชนะ Greedy ทุกตัวชี้วัด** ผลเฉลี่ย DP score117.88 / ใช้งบเต็ม76.25% เทียบ Greedy density score125.46 / ใช้งบเต็ม72.97% ขอบเขตและค่าจริงอยู่ใน [EVALUATION.md](EVALUATION.md)

## Trust boundary และข้อมูลแพ้อาหาร

Python สร้าง trusted facts จาก SQLite; Rego policy `shiro-4.2` schema2 เทียบ raw allergen/dietary sets แม้ Python flagsเป็นfalse แต่ OPA ยังใช้ facts จาก Pythonและdenyเมื่อ python_issues ไม่ว่าง จึงไม่ได้เป็นระบบอิสระจากกันโดยสมบูรณ์ OPA หาย/timeout/outputผิด → fail closed

`strict` รับผู้แพ้เฉพาะรายการที่ allergen_status confirmed และไม่ชนแท็ก; unknown/team_reviewed ไม่ปลด strict การดูชุดจำลองต้อง opt-in เองและยังมีคำเตือน ไม่ใช้ชื่อเมนูแทนหลักฐานสูตรหรือรับประกันปนเปื้อนข้าม

## Action plan: งบต่ำเมื่อเทียบกับจำนวนคน — แก้แล้ว

เกณฑ์ผลิตภัณฑ์ใน `optimization_config.py` คือ `MIN_INTAKE_BUDGET_PER_PERSON=100.0` เทียบ **งบเต็ม ÷ จำนวนคน** ไม่ใช่ยอดหลังกันสำรอง และไม่ใช่การรับรองความอิ่ม/ราคา อาหารที่แบ่งกัน/ปริมาณไม่ถูกประมาณในกฎนี้

`IntakeMixin.intake_budget_warning()` ทำงานหลังทราบงบ/คน ก่อนสรุปยืนยัน และตรวจซ้ำใน `_confirm_order`/planning entry; หากต่ำกว่าเกณฑ์จะปิด confirmation, clear choices, ตั้ง last_asked_field=budget และบันทึก safe intake_check โดยคงงบเดิม/คน/แพ้/ชอบ/ไม่ชอบ/ข้อห้าม พิมพ์ตัวเลขงบใหม่ได้โดยไม่เรียก extractionซ้ำ ยืนยันอย่างเดียวข้ามกฎไม่ได้

การคัดกรองนี้ใช้ใน consumer intake ไม่แก้ positive-budget schemaของ direct MCP หรือ objectiveของ DP ซึ่งยังใช้ทดสอบ numeric feasibilityแยกได้ ไม่ใช่การเพิ่มราคาข้อมูลร้านให้เป็นconfirmed ผล liveที่เก็บไว้ยังเป็น commit426b48aก่อนกฎนี้ ต้องใช้ workflowรอบใหม่หากต้องการหลักฐานproviderของกฎใหม่

## ข้อจำกัดที่ยังเหลือ

- ข้อมูลราคา/ส่วนผสม42รายการยัง unverified/unknown; ไม่มีหลักฐานร้านใหม่ในชุดส่งนี้
- Live ผ่านเฉพาะ5sessions/12goldที่ระบุ ไม่ใช่ human preference study หรือคุณภาพทุก prompt
- Session persistence มีอายุ 24 ชั่วโมงใน SQLite บนเครื่องที่รันแอป; ไม่ใช่บัญชีผู้ใช้หรือ durable storage ข้าม Cloud restart/redeploy
- MCP เปิด subprocess ต่อ planning turn และมี rechecks หลายรอบ ยังไม่ได้พิสูจน์ latency improvement เชิงควบคุม
- ไม่คำนวณ portion/ความอิ่ม/ภาษี/service charge และไม่ส่งออเดอร์จริง

## การจัดชุด GitHub สำหรับส่งตรวจ

เก็บ entrypoint, CSV, dependencies, runtime package, policy และ OPA executable ที่ Cloud ใช้ไว้ รวมผลเก่าให้เหลือ [หลักฐาน7ไฟล์](EVALUATION.md#หลักฐานปัจจุบัน) และเอกสารหลัก4ไฟล์ ลบ RAG/LLM terminal/CLI ทดลองและ packager เก่าที่ไม่ได้อยู่ในเส้นทางแอป ประวัติก่อนจัดชุดอยู่ที่ commit3af6b28; ตำแหน่ง Streamlit เดิมคือ `Shiro-Jung-Agent-v4/app.py`
