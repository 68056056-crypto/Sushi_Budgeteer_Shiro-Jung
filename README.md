# Shiro-Jung 4.0 — Sushi Budgeteer

โครงงานผู้ช่วยวางแผนมื้อซูชิด้วย LLM, MCP, SQLite, DP และ OPA

**ทดลองแอป:** https://shiro-jung.streamlit.app/

เอกสารสำหรับอาจารย์:

- [ภาพรวมและวิธีรัน](Shiro-Jung-Agent-v4/README.md)
- [Code Review และเงื่อนไขระบบ](Shiro-Jung-Agent-v4/CODE_REVIEW.md)
- [Evaluation และหลักฐาน Live LLM](Shiro-Jung-Agent-v4/EVALUATION.md)
- [Data Dictionary และข้อจำกัดข้อมูลร้าน](Shiro-Jung-Agent-v4/DATA_DICTIONARY.md)

โค้ดอยู่ใน [Shiro-Jung-Agent-v4](Shiro-Jung-Agent-v4) และ entrypoint ของ Streamlit Cloud คงเป็น **`Shiro-Jung-Agent-v4/app.py`** บน `main`

Live รุ่น4.4.0 ผ่านแล้วบน source`0f0b161`: [Actions run39899787025](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39899787025) corpus6sessions/14gold และบังคับมี model-selected build/verify อย่างน้อย1ครั้ง ยืนยันจากสถานะงาน/ขั้นประเมินและ exit contract; ยังดาวน์โหลดraw artifactรอบใหม่จากเครื่องนี้ไม่ได้ จึงเก็บJSON/traceเก่าsource426b48aเป็นหลักฐานประวัติที่แยกชัดเจน ดูรายละเอียดใน EVALUATION ข้อมูลร้านยังไม่ยืนยันและยกเว้นการเก็บหลักฐานในรอบนี้ สไลด์/Word/PDFไม่อยู่ในrepository
