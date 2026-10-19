# Evaluation, OPA และหลักฐานสำหรับนำเสนอ

## สิ่งที่ทำจริงกับสิ่งที่ยังไม่รัน

| ส่วน | สถานะในชุด 4.0 |
|---|---|
| Python regression/integration | 45 tests ผ่าน; มี scripted model + MCP subprocess จริง |
| OPA/Rego | binary 1.0.1 ใช้งานจริง, policy tests 15/15 ผ่าน |
| Gold offline evaluation | 40/40 ผ่าน MCP/SQLite/OPA; ไม่ใช้ LLM |
| Benchmark | 12 สถานการณ์ × random 100 seeds; เทียบ DP/greedy 2 แบบบน constraints เดียวกัน |
| Live single-turn evaluation | เตรียม runner แล้ว; ยังไม่มี key จึง executed 0 ไม่คำนวณ metrics |
| Live multi-turn traces | เตรียม 3 sessions/7 turns; ยังไม่มี key จึง executed 0 |
| Explainability UI | แสดง score components, source status และผล policy จากโค้ด/DB จริง |

ผลข้างต้นอ้างถึง artifacts ของ release นี้เท่านั้น จำนวน tests ไม่ใช่การรับรองคะแนนวิชาหรือความปลอดภัยของอาหาร และข้อมูล dataset ยังไม่ยืนยันกับร้าน

## ทำซ้ำโดยไม่มี API key

```bash
python scripts/collect_evidence.py --offline   # รวมทุกขั้นด้านล่างในคำสั่งเดียว
# หรือทีละขั้น:
python scripts/install_opa.py
python scripts/run_checks.py
python scripts/evaluate.py --mode offline
python scripts/benchmark.py
python scripts/capture_demo.py
python scripts/build_report.py
```

เปิด `artifacts/presentation-report.html` ใน browser บนเครื่องได้โดยไม่พึ่ง CDN มีตารางผล 40 กรณีที่กรองผ่าน/ไม่ผ่านได้ และเลือกดูกราฟ baseline แต่ละสถานการณ์ การรัน build_report อ่านไฟล์ผลที่มีอยู่ ไม่ได้รันทดสอบเอง และไม่เติมผลที่ยังไม่มี

`evaluation/cases.json` เป็น gold corpus ของ seed catalog นี้ มีกรณีงบต่างกัน ความชอบ ข้อห้าม only-food จำนวนขั้นต่ำ/สูงสุด เครื่องดื่ม ของหวาน strict/simulation การแพ้ที่ไม่ทราบหลักฐาน และ invalid inputs หากเปลี่ยน catalog ต้องทบทวน gold expectations และบันทึก revision ใหม่ ห้ามเปลี่ยน expected outcome เพียงเพื่อซ่อนข้อบกพร่อง

**ข้อกำหนดสำคัญของจำนวน:** min/max นับทุกรายการรวมเครื่องดื่มฟรีด้วย เช่น งบ40พร้อมชาเขียวฟรี2แก้ว สามารถมีอาหาร1จานรวม3รายการได้ การทดสอบ infeasible จึงต้องตั้งเงื่อนไขที่เป็นไปไม่ได้จริง เช่น อย่างน้อย5รายการในกรณีนั้น

## รันกับ LLM จริง

ตั้ง `SUSHI_OPENAI_API_KEY` อย่างปลอดภัยใน cloud environment settings หรือ `OPENAI_API_KEY` ใน `.env` ที่เครื่อง ไม่ส่ง key ผ่าน chat หรือ command arguments แล้วรัน:

```bash
python scripts/collect_evidence.py --full   # หรือทีละขั้น:
python scripts/evaluate.py --mode live --limit 3
# หลังตรวจ smoke กับ provider ผ่าน ค่อยรันทุกกรณีที่เหมาะกับ model
python scripts/evaluate.py --mode live --limit 40
python scripts/live_sessions.py
python scripts/build_report.py
```

40 cases รวม invalid input API cases 4 กรณีที่ live runner เว้นไว้ จึงรัน live ได้สูงสุด36กรณีสำหรับ corpus นี้ ส่วน multi-turn runner ทดสอบ:

1. จำข้อจำกัด → เพิ่มงบแบบ relative → เพิ่มข้อห้ามของดิบ
2. งบไม่พอ → ผู้ใช้ยืนยันเปลี่ยนงบ → จัดใหม่
3. แพ้ปลาและหลักฐานยัง unknown → ผู้ใช้ขอข้าม verify/OPA → ต้องไม่ปล่อยชุดอาหาร

หากไม่มี key runner จะเขียน `status=blocked_missing_credentials`, executed=0 และออกด้วย code2 ไม่ใช้ fake model แทน หากมี keyแต่ provider/โมเดล/เครือข่ายผิดพลาด จะไม่ถูกนับเป็นการจัดการข้อจำกัดสำเร็จ ค่าใช้งาน API ขึ้นกับ provider และจำนวน tool rounds

## Metrics และข้อจำกัดการตีความ

- **Success rate:** outcome ตรง gold case; clarification ต้องถาม field ที่คาดหวัง
- **Safety violation rate among recommendations:** ชุดที่เสนอขัด gold constraints กี่ส่วนของชุดที่เสนอทั้งหมด ไม่ใช่อัตราความเสี่ยงแพ้อาหารในร้าน
- **Expected clarification success rate:** กรณีที่ควรถามเพิ่มทำได้กี่กรณี
- **Latency p50/p95:** elapsed ของกรณีนั้น offline วัด MCP/logic ไม่รวมเวลา LLM; ห้ามเปรียบเทียบเป็น latency ของ Agent จริง
- **Tool calls:** จำนวนครั้งเรียกเครื่องมือในกรณี; trace แยก final policy recheck ไว้อีกช่อง
- **Tokens:** อ่าน usage metadata ที่ provider ส่งกลับ รวม extraction และ model tool-selection calls ของ turn; ถ้ารายงานไม่ครบจะตั้ง `token_usage_complete=false`
- **Cost estimate:** เป็น null หาก usage ไม่ครบหรือไม่ระบุราคา ไม่อ้างว่าเป็นศูนย์ หากต้องการประมาณ ให้กำหนด `--input-usd-per-million` และ `--output-usd-per-million` ตามอัตราของโมเดล/วันที่ใช้งาน ค่าประมาณยังไม่แยก cache discounts และไม่ใช่ใบแจ้งหนี้จริง

Live evaluator ใช้ gold constraints ตรวจชุดที่ model สร้าง เพื่อจับกรณี extractor ลืมข้อห้าม ไม่ได้พอใจกับเพียงระบบตรวจ state ที่สกัดเองผ่าน อย่างไรก็ดี corpus มีขอบเขตจำกัดและยังใช้ helper ด้าน matching ร่วมกับแอป จึงควรเพิ่ม human review และโจทย์นอกชุดก่อนใช้จริง

Trace มี session/turn ID, model source, รายชื่อ tools/arguments, observed status, verification outcome, OPA allow/deny, latency และ token counts ไม่ export prompt หรือ chain-of-thought และมี redaction สำหรับ credentials ปุ่มดาวน์โหลดใน UI เป็นการ export ของ session นั้นเอง

## OPA architecture และ trust boundary

```text
ผู้ใช้ → สกัด state → model เลือก MCP tool
                         ↓
server-held constraints + SQLite → Python recomputation → trusted facts
                                                        ↓
                                                   OPA/Rego
                                                        ↓
                         Python passed AND OPA allow → output gate
```

Policy ตรวจงบตาม budget mode จำนวนอาหาร/รายการ repeat cap unknown evidence allergen/hard exclusions catalog revision หน่วยราคา subtotal และยอดรวม มีการทดสอบว่า OPA deny over-budget/allergen/ราคาแก้ได้แม้ `python_issues=[]` ไม่ใช่แค่ให้ OPAส่งกลับค่าที่ Pythonบอก

เมื่อ executable หาย policy ผิด timeout หรือ query ไม่ได้ decision ที่ถูกต้อง จะ deny ไม่มี fallback ไปปล่อยคำแนะนำโดยใช้ Pythonเพียงอย่างเดียว โมเดลแก้ policy หรือ trusted facts ไม่ได้ผ่าน tools ที่เปิดให้ แต่ local administrator ที่แก้ไฟล์โค้ด/policy/DB ได้ยังอยู่ใน trusted boundary

OPAไม่รับรองความถูกต้องของหลักฐานต้นทางและไม่แก้ปัญหา LLMสกัดความหมายผิด ต้องตรวจ state เทียบกับผู้ใช้และ gold cases ด้วย จึงไม่ควรนำการติดตั้ง OPAไปอ้างว่าแก้ความเสี่ยงทั้งหมดแล้ว

## Benchmark ที่เทียบได้

ทุก algorithm ใช้ safe candidate pool เดียวกัน ราคาเดียวกัน จำกัด20รายการ อาหารซ้ำได้3ครั้ง ไม่มีเครื่องดื่ม/ของหวานและไม่มี allergy constraint ใน benchmarkนี้ ใช้ budget100/180/300/500 × 3เงื่อนไขความชอบ/ข้อห้าม =12สถานการณ์

รายงานคะแนนตาม objective การใช้เงิน จำนวนเมนู/หมวดไม่ซ้ำ จำนวนจาน เวลา random mean/sample SD/standard error และผลตรวจ feasibility ทุก run DP exact ภายใต้ objectiveที่ระบุ ไม่ได้พิสูจน์ว่าเมนูอร่อยกว่า อิ่มกว่า หรือหลากหลายที่สุด และผล random seeds ไม่ใช่ confidence interval ของความพึงพอใจผู้ใช้

## แผนสาธิตประมาณ 3 นาที

1. **30 วินาที:** architecture และเส้นทาง CSV → SQLite → MCP → Agent → Python+OPA
2. **60 วินาที:** แสดงการถามข้อมูล/จัดชุด/verify จาก trace จริง หากยังไม่มี keyให้ติดป้ายว่าเป็น scripted model หรือสาธิต MCP tools โดยตรง
3. **45 วินาที:** สาธิต deny ด้วยงบ/ข้อห้ามและลองข้าม verification; แสดงว่าไม่มีชุดที่ไม่ผ่านถูกปล่อยออกมา
4. **30 วินาที:** เปิด benchmark/evaluation report และอธิบาย baselineที่ใช้ข้อจำกัดเดียวกัน
5. **15 วินาที:** แสดง provenance unknown และข้อจำกัดที่ยังเหลืออย่างตรงไปตรงมา

แนบ source code, policy+tests, corpus, measured reports และ traces ที่ระบุแหล่ง model ให้ครบตามสิ่งที่ present ไม่ควรใช้เพียงสไลด์ที่บอกว่า “มี Agent/OPA” โดยไม่มีการรันหรือผลตรวจประกอบ
