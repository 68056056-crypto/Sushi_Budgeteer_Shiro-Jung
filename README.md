# Shiro-Jung 4.0 — Sushi Budgeteer

โครงงานผู้ช่วยวางแผนมื้อซูชิด้วย LLM, MCP, SQLite, DP และ OPA

**ทดลองแอป:** https://shiro-jung.streamlit.app/

เอกสารสำหรับอาจารย์:

- [ภาพรวมและวิธีรัน](Shiro-Jung-Agent-v4/README.md)
- [Code Review และเงื่อนไขระบบ](Shiro-Jung-Agent-v4/CODE_REVIEW.md)
- [Evaluation และหลักฐาน Live LLM](Shiro-Jung-Agent-v4/EVALUATION.md)
- [Data Dictionary และข้อจำกัดข้อมูลร้าน](Shiro-Jung-Agent-v4/DATA_DICTIONARY.md)

โค้ดอยู่ใน [Shiro-Jung-Agent-v4](Shiro-Jung-Agent-v4) และ entrypoint ของ Streamlit Cloud คงเป็น **`Shiro-Jung-Agent-v4/app.py`** บน `main`

ผล live ที่ตรวจแล้ว: 5 sessions, gold12/12, model-selected recommendations6 จาก [Actions run39799552734](https://github.com/68056056-crypto/Sushi_Budgeteer_Shiro-Jung/actions/runs/39799552734) ผลนี้เป็น source commit เดิม ไม่ใช่ live rerun ของ package4.4.0 ซึ่งเพิ่ม required menu, explicit-cap diversity, intake100บาทต่อคน และ session persistence ดูผลปัจจุบันใน EVALUATION ข้อมูลราคา/สารก่อภูมิแพ้ยังไม่ยืนยันกับร้าน สไลด์/Word/PDF จัดส่งแยกจาก repository
