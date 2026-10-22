# ตอบข้อเสนอแนะอาจารย์ รอบ 2 และรอบติดตาม

โครงงาน Shiro-Jung Agent 4.0 / implementation 4.2.1 ตรวจ 22 ตุลาคม 2569 ไม่มีการประเมินคะแนนใหม่ให้ตนเอง

## ข้อเสนอแนะล่าสุด เรียงตามความสำคัญ

| ข้อเสนอแนะ | การแก้ไขที่ทำแล้ว | สถานะ / หลักฐาน |
|---|---|---|
| ไม่กิน X ต้อง hard | เพิ่มกฎหลัง extraction สำหรับไม่กิน/ไม่ทาน/งด/ห้าม ลบ soft alias เดิมด้วย ไม่เปลี่ยน soft “ไม่ค่อยชอบ” เป็น hard | แก้แล้ว; test_explicit_refusals.py รวม scenario 1500 บาท 2 คน แพ้กุ้ง ชอบแซลมอน ไม่กินหมู |
| Live LLM | เพิ่ม workflow แบบ manual, secure secret env, ตรวจ state และ success, model-selected gate และ export trace 1 session | ยืนยัน Actions run 39799552734 ที่ commit426b48a: live=true, 12/12 gold, 18 turns, 31 responses, 6 model-selected recommendations, errors0 |
| ข้อมูลร้าน | เพิ่ม team_reviewed พร้อมเหตุผล/ผู้ตรวจ/วันที่ ไม่ปลด strict; ราคา confirmed ต้องมีแหล่งหลักฐาน/วันที่ เตรียมคำถาม 15 เมนูและ checklist สาขา/ภาพป้าย | ยังไม่มีภาพป้าย/คำตอบร้านและยังไม่ได้ส่งข้อความ รักษา unknown/unverified ทั้ง 42 เมนู |
| ชุดที่สองใกล้ซ้ำ | ตัดกลุ่มเมนูคะแนนสูงและตรวจชื่อเมนูอาหารเดิมที่หายไป ≥30%; คงข้อจำกัด/ส่วนเพิ่ม ลองได้สูงสุด 3 กลุ่ม | แก้แล้ว; ถ้าทำไม่ได้เสนอชุดเดียว ไม่ผ่อนการแพ้หรืองบเพื่อสร้างทางเลือก |
| State persistence | ยังใช้ Streamlit session state; SQLite เก็บ catalog เท่านั้น | ยังไม่ทำตามทางเลือกในข้อเสนอแนะ ระบุข้อจำกัดในเอกสารและสไลด์ชัดเจน |

## ข้อเสนอแนะรอบ 2 เดิมที่ยังคงอธิบายตามจริง

- คำว่าเนื้อที่ไม่ระบุชนิดถามครั้งเดียวให้เลือกหมู/วัว/ไก่/สัตว์บกทั้งหมด แยกไม่ชอบ/ไม่กิน/แพ้ตามผู้ใช้ และไม่ตัดปลา/อาหารทะเลเพียงเพราะเลือกสัตว์บก
- แยก Agent เป็น intake/planning/checkout mixins คง public API และ shared session state; ไม่อ้างว่าลด shared-state coupling หมดแล้ว
- bounded exact DP ดีที่สุดตาม objective ที่นิยาม ไม่ใช่ทุกตัวชี้วัด: ภายในช่วง ≥95% ของวงเงินอาหารให้คะแนนก่อน หากช่วงนั้นทำไม่ได้ให้ยอดใช้จ่ายก่อน Greedy density ได้คะแนนเฉลี่ย 117.44 ขณะที่ DP 110.77
- วงเงินอาหารเริ่มต้น 80% ของงบเต็ม ผล benchmark DP ใช้งบเต็มเฉลี่ย 76.25% หรือ 95.3125% ของวงเงินอาหาร ไม่ได้หมายความว่าใช้เงินครบ 80% ทุกกรณี เงื่อนไข/เพดานจำนวนอาจทำให้ไม่ถึงเป้า
- 40 offline gold scenarios ไม่เรียก LLM; Agent integration ใช้ scripted model กับ MCP/SQLite/OPA จริง ไม่รวมเป็นหลักฐาน provider จริง

## ผลตรวจหลังแก้

165 regression/integration tests, 25 Rego tests, smoke 61 ต่อโหมด, offline gold 40/40 ดู checked_at/release จาก artifacts/review-live-confirmed-checks/validation-report.json ไม่ใช้ผลเหล่านี้รับรองสูตรร้าน ความพึงพอใจจริง หรือ live-model quality

## สิ่งที่ทีมต้องเติมจากหลักฐานจริง

1. ปิดประเด็นหลักฐาน live แล้วตาม run39799552734: เก็บ JSON ต้นฉบับ/trace/SHA256 และใส่ trace จริง 1 session ในสไลด์ ผลจำกัดที่ commit426b48a และ corpus นี้ การปรับ snapshot/parser หลังจากนั้นยังต้องแยกจากผล live เดิม
2. ถ่ายป้ายราคา/สีจานที่สาขาพร้อมวันที่ ส่งร่างคำถามรายเมนูจาก RESTAURANT_VERIFICATION.md ผ่านช่องทางทางการที่ทีมเลือก เก็บคำตอบและขอบเขตสาขา/วันที่
3. ทีมอ่านหลักฐานรายเมนูและลงชื่อ/เหตุผลก่อนใช้ team_reviewed หากร้านไม่ยืนยัน ห้ามเปลี่ยนเป็น confirmed เอง ห้ามลบแท็กสารที่อาจมีเพียงเพราะร้านไม่ตอบ
4. สไลด์/Word/PDF จัดส่งแยกเพื่อดาวน์โหลด ไม่อัปโหลด GitHub ระบบแชตผู้บริโภคไม่แสดง trace หรือรายละเอียดเทคนิคเหล่านี้


## เพิ่มการวินิจฉัย provider

เพิ่ม 5 diagnostic regression tests ด้วย synthetic exceptions ไม่เรียก API จริง แยก authentication/quota/transport และ JSON validation failure เก็บ metadata ปลอดภัยใน run report/job summary เพื่อให้แก้ปัญหาจากหลักฐานแทนเดา ค่า live ยังต้องพิจารณาจากผล workflow ของ commit ที่รันจริง


เพิ่ม credential format preflight: trim หัวท้าย, reject internal control characters/embedded whitespace/multiple settings ก่อน HTTP request โดยไม่เผย secret การทดสอบนี้ยืนยันการตรวจรูปแบบ ไม่ใช่ผลเรียก API จริง


ปรับตัวตรวจคีย์ให้แกะ clipboard wrappers เช่น quotes/prefix ที่ขอบได้ โดยยังปฏิเสธหลายบรรทัดหรือเนื้อหาภายในผิดรูปแบบ และเพิ่มชื่อสาเหตุใน job summary เพื่อไม่ให้ผู้ใช้ลองแก้ Secret แบบไม่มีข้อมูล ไม่แสดงคีย์หรืออักขระจริง


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
