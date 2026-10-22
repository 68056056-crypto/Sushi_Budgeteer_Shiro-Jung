# คำตอบผลประเมินรอบ 2 — Shiro-Jung 4.2.0

สรุปการแก้ไขวันที่ 22 ตุลาคม 2569 ตาม 6 ประเด็นที่ได้รับ เอกสารประเมินที่ผู้ใช้แนบรายงาน 31/35 เป็นคะแนนจากผู้ประเมิน ไม่ใช่การคาดการณ์คะแนนหลังแก้รอบนี้

| ประเด็น | สิ่งที่ทำ | สถานะ |
|---|---|---|
| Live LLM ยังไม่รัน | ตรวจ credentials และเรียก runner จริงให้บันทึกสถานะ เพิ่ม corpus 5 sessions / 12 gold turns ครอบคลุมชนิดเนื้อและ explicit opt-in; ทดสอบ orchestration แบบ offline โดยไม่ตี scripted เป็น live | ยังไม่มี credentials: `live_llm_tested=false`, 0 live turns |
| ข้อมูลร้าน unknown/unverified | Audit ครบ42เมนูและส่งออก checklist สำหรับเติม URL ส่วนผสม/ราคา วันที่ตรวจ และบันทึกผู้ตรวจ ไม่เปลี่ยนสถานะเอง | ยังรอหลักฐานร้าน: allergen42/42 unknown, ราคา42/42 unverified |
| Greedy score สูงกว่า DP | รัน production benchmark ใหม่ รายงาน DP110.77 / Greedy density117.44 และลำดับ objective อย่างตรงไปตรงมา | แก้เอกสารและสไลด์แล้ว |
| ไม่กินเนื้อไม่ตัดเมนู | หน้าเว็บถามชนิดหมู/วัว/ไก่/สัตว์บกทั้งหมด โดยคงไม่ชอบ/ไม่กิน/แพ้ต่างกัน รักษางบและการแพ้อื่น; direct hard-filter รองรับกลุ่มเนื้อสัตว์บก | แก้และทดสอบทั้ง UI/Agent/filter/OPA |
| ใช้จริง76%ของงบ | ระบุตัวหารสองค่า: 76.25% ของงบเต็ม /95.3125% ของวงเงินอาหาร80%; ใช้เงินเหลือเพิ่มน้ำ/ขนมได้ถึงงบเต็ม | แก้เอกสารและสไลด์แล้ว |
| agent.py เกือบ1000บรรทัด | แยก intake/planning/checkout เป็น mixins และเก็บ lifecycle/routing ใน Agent เดิม รักษา API/session state/guards | Refactor แล้ว และ regression ผ่าน |

## ผลตรวจรอบนี้

- Regression/integration **139 tests** ผ่าน, errors/failures0
- OPA **25 tests** ผ่าน; เพิ่มกฎตรวจการแพ้สัตว์บกจาก raw dietary tags แม้ flag Pythonเป็นfalse
- Smoke **61 checks ต่อโหมด** ผ่านทั้งstrictและsimulation
- Offline gold **40/40** โดยเรียกMCP/SQLite/OPAตรง ไม่มีLLM ส่วนAgent regression/harnessใช้scripted model แยกกัน
- Benchmark **12 สถานการณ์ ×100 Random seeds =1,200 runs**; ไม่มีfeasibility/objective-dominance failure ในชุดนี้

ดูผลจริงใน `artifacts/review-round2/` และขอบเขตใน [EVALUATION.md](EVALUATION.md) ไม่มีการใช้ผล scripted แทนหลักฐาน provider จริง และไม่ได้รับรองสูตรร้านจากทะเบียนสารก่อภูมิแพ้10กลุ่ม

## ข้อความแนะนำสำหรับนำเสนอ

> “DP ของเราหาคำตอบที่ดีที่สุดตามลำดับ objective ที่กำหนด ถ้ามีชุดในช่วง95–100%ของวงเงินอาหาร จะเลือกคะแนนลดซ้ำสูงสุด แล้วใช้ยอดเงินเป็นตัวตัดสินกรณีคะแนนเท่ากัน ถ้าเข้าไม่ถึงช่วงนั้น จะเลือกใช้เงินได้มากสุดภายใต้ข้อจำกัดก่อน ดังนั้น Greedy อาจได้ raw score หรือความหลากหลายสูงกว่า DP ได้ เราไม่ได้อ้างว่าชนะทุกตัวชี้วัด”

> “วงเงินจัดอาหารเริ่มต้นเป็น80%ของงบผู้ใช้ เพื่อเหลือเงินให้ตัดสินใจเพิ่มน้ำหรือขนมภายหลัง ค่าเฉลี่ยการทดลองนี้ใช้76.25%ของงบเต็ม หรือ95.3125%ของวงเงินอาหาร ไม่ใช่ใช้95%ของงบผู้ใช้ การคิดเงินตอนสรุปสุดท้ายรวมส่วนเพิ่มต้องอยู่ในงบเต็ม”

> “live LLM ยังไม่ผ่านการทดสอบใน environment นี้ ข้อมูลสูตรร้านและราคายังไม่ยืนยัน เราแยกสิ่งที่ทดสอบกับtoolsจริงออกจากผลจำลองของAgentอย่างชัดเจน และไม่ตั้งconfirmedขึ้นเอง”

## ขั้นตอนปิดสองข้อที่ยังค้าง

1. ตั้ง API key ใน environment/secrets อย่างปลอดภัยและรัน `python scripts/live_sessions.py --scenarios evaluation/round2_sessions.json --output artifacts/review-round2/live-status.json` ตรวจทั้งusage, source, constraints, mode, consent และผลรายturnก่อนอ้างความสามารถจริง
2. ใช้ `python scripts/catalog_audit.py --checklist <path.csv>` แล้วให้ผู้ตรวจเติมหลักฐานเมนูจริง เริ่ม10–15เมนูที่เอกสารส่วนผสมครอบคลุมซอส/ท็อปปิง/การปนเปื้อน พร้อมแหล่งราคาและวันที่ ตรวจต้นฉบับก่อนเปลี่ยนสถานะในcatalog ไม่ใช้fixtureในtestsเป็นหลักฐานร้าน

ไฟล์นำเสนอและเอกสารส่งอาจารย์เก็บแยกจากrepositoryตามที่ผู้ใช้ระบุ ไม่ส่งPowerPoint/PDF/Wordขึ้นGitHub
