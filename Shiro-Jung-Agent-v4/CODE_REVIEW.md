# ผลตรวจและการแก้ไข (release 4.0 ต่อยอดจาก 3.0)

## เพิ่มใน 4.0

| ประเด็นจากการตรวจ v3 | การแก้ไขใน v4 |
|---|---|
| README สั่ง `cd Sushi_Budgeteer_Shiro-Jung` แต่โฟลเดอร์ชื่ออื่น | ใช้ชื่อ `Shiro-Jung-Agent-v4` ทุกที่ รวม `mcp-config.example.json` และ package script |
| Artifacts มี absolute path ของ cloud (`/workspace/...`) | `database.display_path()` รายงาน path แบบ relative; `run_checks.py` ตัด root path ออกจากผล OPA |
| ไฟล์ซ้ำ `.env.example.env` | ลบออก เหลือ `.env.example` ไฟล์เดียว |
| ขั้นตอนเก็บหลักฐานกระจายหลายคำสั่ง และ `setup.sh` ใช้บน Windows ไม่ได้ | เพิ่ม `scripts/collect_evidence.py` รันครบทุกขั้นข้ามแพลตฟอร์ม, บังคับ UTF-8, refresh database/MCP logs |
| `database-import.json`, `database-status.json`, `mcp-demo.log` ไม่ถูกสร้างใหม่อัตโนมัติ | collect_evidence เขียนไฟล์เหล่านี้ทุกครั้ง |
| validation report ไม่ระบุ release/platform | เพิ่ม `release` และ `platform` |

สิ่งที่ **ยังไม่เปลี่ยน** ใน 4.0: live LLM evaluation ยังเป็น `blocked_missing_credentials` จนกว่าจะรันด้วย key จริง และยังไม่ได้ทดสอบบน Windows/macOS จริง

## ผลตรวจและการแก้ไขใน release 3.0

เอกสารนี้แทนรายงานก่อนหน้าที่ตรวจพบ defects งานรอบนี้แก้ application code ตามคำขอให้ส่งชุดใช้งานได้ พร้อม regression tests และข้อมูล provenance ดูผลที่รันจริงใน `artifacts/validation-report.json`

| ข้อค้นพบเดิม | การแก้ไขและหลักฐาน |
|---|---|
| Agent ถูก cache แชร์ข้ามผู้ใช้ | เลิก `st.cache_resource`; object เก็บใน session; tests ตรวจแยก state |
| ผลลัพธ์ global อาจ verify ผิดชุด | เส้นทางจริงใช้ MenuService ต่อ subprocess + result UUID + trusted constraints; ตรวจ ID คนละ service ไม่ผ่าน |
| verify เป็นแค่ prompt | Python output gate บล็อก model prose/candidate ที่ยังไม่ verify; ตรวจซ้ำจาก MCP ก่อน render |
| DP พลาด optimum เมื่อจำกัดจำนวน | เพิ่ม count dimension; counterexample เดิมได้ 6 แทน 5; เทียบ exhaustive search 35 fixtures |
| เงินทศนิยมปัดเป็นบาทจนเกินงบ | ใช้ integer satang และ validate 2 ตำแหน่ง |
| ไม่ enforce min/max/free drink only | Builder/validator ตรวจจำนวนและต้องมีอาหารอย่างน้อย 1 จาน |
| drinks/dessert ข้าม allergen filter | กรอง fixed items ก่อนจัดชุด และตรวจทุก item จาก catalog อีกครั้ง |
| ราคา/จำนวนในผลถูกแก้แล้วยังเชื่อ | คำนวณจาก catalog ใหม่ ตรวจ quantity/subtotal/ยอดรวม/revision; มี tamper tests |
| random baseline repeat cap ต่างจาก DP | ใช้ expanded pool ซ้ำได้ 3 เท่ากัน; benchmark 100 seeds |
| CSV ไม่มี provenance status | เพิ่ม source/price/allergen status; unknown default; strict fail closed |
| MCP 2 ทำ import พัง | pin MCP 1.30 และจัด hash-locked dependencies; ทดสอบใน venv ใหม่ |
| RAG build เป็นเส้นทางข้าม constraints | ไม่เปิด RAG ใน MCP release; legacy wrapper ใช้ shared builder |
| UI ไม่แสดง disclaimer ถาวร | เพิ่ม warning ถาวรและแสดงทุกคำตอบชุดอาหาร |

**แก้ข้อมูลในรายงานเดิม:** การอ่านไฟล์ที่ต่อกันทำให้รายงานก่อนหน้าระบุผิดว่า `.env.example.env` มี model ลงท้าย `.env` และ `.gitignore` ไม่กัน `.env` ตรวจไฟล์แยกแล้วต้นฉบับใช้ `gpt-4o-mini` และ ignore `.env` อยู่แล้ว รอบนี้จัดตัวอย่าง `.env.example` และขยาย ignore patterns โดยไม่อ้างว่าแก้ defect สองเรื่องนั้น

## ขอบเขตของหลักฐาน

- Tests ของ Agent ใช้ scripted fake model แต่เปิด MCP subprocess และ query SQLite จริง ไม่ใช่การทดสอบ OpenAI จริง
- ไม่มี credential สำหรับยืนยัน model selection/tool arguments กับ provider จริง หรือ embeddings/RAG
- official menu/PDF ยังเข้าไม่ได้จาก cloud จึงไม่รับรองราคาและ allergen ปัจจุบัน
- strict mode บล็อก allergy recommendations จาก seed data ที่ unknown; simulation มีไว้ทดลองเท่านั้น
- Python validator ทำงานร่วมกับ OPA/Rego แบบ fail closed แล้ว; ยังไม่มี persistent chat storage/authentication สำหรับ network deployment (MCP จำกัด stdio)
- exact DP หมายถึง optimum ตาม objective คะแนนที่ระบุ ภายใน candidate catalog และขอบเขตทรัพยากร ไม่ใช่ optimum ของโภชนาการ ความอิ่ม หรือความหลากหลายจริงทุกมิติ
- ภาษาไทย/ชื่อเมนูอาศัย LLM และ fuzzy matching จึงอาจสกัดหรือจับคู่ผิด ต้องตรวจ sidebar และเพิ่ม production scenarios ก่อนเปิดใช้จริง
- legacy direct tools ยังมี thread-local last-result compatibility สำหรับ smoke tests; Agent/MCP release ไม่ใช้มันเป็นที่เก็บผลข้าม request และ external clients ควรใช้ result_id API

ก่อนนำเสนอควรตั้ง key แล้วเก็บ trace จริงสำหรับข้อมูลไม่ครบ → ค้นหา → จัดชุด → ตรวจผล และกรณีไม่ผ่าน → ถามใหม่ พร้อมรายงานสิ่งที่ยังไม่ตรวจ ห้ามนำ traces แบบ scripted ไปอ้างว่าเป็นการตัดสินใจของ LLM จริง

## เพิ่มใน 3.0

- OPA executable ตรวจ checksum จาก release ทางการก่อนใช้; Rego tests 15 กรณี และ integration tests ตรวจ fail closed เมื่อ binary หาย
- Trace แยก model source, tool events, final recheck, latency, provider token usage และ redaction
- Gold corpus 40 กรณีสำหรับ offline MCP evaluation; live runner แยกกับ 3 multi-turn sessions (7 turns)
- Benchmark 12 สถานการณ์ เทียบ DP/greedy/random ภายใต้ข้อจำกัดเดียวกัน รวม random 1200 runs
- UI แสดง provenance และ score components ที่มาจากสูตรเดียวกับ optimizer พร้อมรายงาน HTML สำหรับนำเสนอ

ผลชุดทดสอบและ corpus เป็นหลักฐานเฉพาะกรณีที่รัน ไม่รับประกันทุกข้อความภาษาไทย และยังไม่ใช้ยืนยันว่า live LLM ทำงานผ่านจนมี credential แล้วรันจริง
