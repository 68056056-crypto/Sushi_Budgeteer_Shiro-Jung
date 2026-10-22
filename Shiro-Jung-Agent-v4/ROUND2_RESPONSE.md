# ตอบข้อเสนอแนะอาจารย์ รอบ 2 และรอบติดตาม

โครงงาน Shiro-Jung Agent 4.0 / implementation 4.2.1 ตรวจ 22 ตุลาคม 2569 ไม่มีการประเมินคะแนนใหม่ให้ตนเอง

## ข้อเสนอแนะล่าสุด เรียงตามความสำคัญ

| ข้อเสนอแนะ | การแก้ไขที่ทำแล้ว | สถานะ / หลักฐาน |
|---|---|---|
| ไม่กิน X ต้อง hard | เพิ่มกฎหลัง extraction สำหรับไม่กิน/ไม่ทาน/งด/ห้าม ลบ soft alias เดิมด้วย ไม่เปลี่ยน soft “ไม่ค่อยชอบ” เป็น hard | แก้แล้ว; test_explicit_refusals.py รวม scenario 1500 บาท 2 คน แพ้กุ้ง ชอบแซลมอน ไม่กินหมู |
| Live LLM | เพิ่ม workflow แบบ manual, secure secret env, ตรวจ state และ success, model-selected gate และ export trace 1 session | ยังไม่มี API key ในเครื่อง และ GitHub Actions token ใช้ไม่ได้ จึงยัง live=false / executed=0 / model-selected-live=0 |
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

161 regression/integration tests, 25 Rego tests, smoke 61 ต่อโหมด, offline gold 40/40 ดู checked_at/release จาก artifacts/review-round2-diagnostics/validation-report.json ไม่ใช้ผลเหล่านี้รับรองสูตรร้าน ความพึงพอใจจริง หรือ live-model quality

## สิ่งที่ทีมต้องเติมจากหลักฐานจริง

1. เพิ่ม secret ใน GitHub Actions แล้วรัน Live LLM evaluation ดาวน์โหลด JSON และ live-trace.md ตรวจ source commit/model/route/success ก่อนใส่ trace 1 session ลงสไลด์ ไม่แสดง API key หรือข้อมูลส่วนบุคคล
2. ถ่ายป้ายราคา/สีจานที่สาขาพร้อมวันที่ ส่งร่างคำถามรายเมนูจาก RESTAURANT_VERIFICATION.md ผ่านช่องทางทางการที่ทีมเลือก เก็บคำตอบและขอบเขตสาขา/วันที่
3. ทีมอ่านหลักฐานรายเมนูและลงชื่อ/เหตุผลก่อนใช้ team_reviewed หากร้านไม่ยืนยัน ห้ามเปลี่ยนเป็น confirmed เอง ห้ามลบแท็กสารที่อาจมีเพียงเพราะร้านไม่ตอบ
4. สไลด์/Word/PDF จัดส่งแยกเพื่อดาวน์โหลด ไม่อัปโหลด GitHub ระบบแชตผู้บริโภคไม่แสดง trace หรือรายละเอียดเทคนิคเหล่านี้


## เพิ่มการวินิจฉัย provider

เพิ่ม 5 diagnostic regression tests ด้วย synthetic exceptions ไม่เรียก API จริง แยก authentication/quota/transport และ JSON validation failure เก็บ metadata ปลอดภัยใน run report/job summary เพื่อให้แก้ปัญหาจากหลักฐานแทนเดา ค่า live ยังต้องพิจารณาจากผล workflow ของ commit ที่รันจริง
