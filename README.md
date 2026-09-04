# 🍣 Sushi-Budgeteer: AI Agent จัดเซ็ตเมนูซูชิตามงบประมาณ

ระบบ **Agentic AI** ที่ใช้ LangGraph ReAct Agent + Dynamic Programming  
จัดชุดเมนู Sushiro ให้คุ้มค่าที่สุดตามงบประมาณและข้อจำกัดของผู้ใช้

---

## โครงสร้างโปรเจกต์

```
NLP Mini Project/
├── app.py                        # Streamlit UI (4 หน้า)
├── sushiro_menu_dataset.csv      # ฐานข้อมูลเมนู (44 รายการ + allergens_verified)
├── requirements.txt
├── .env.example
└── sushi_budgeteer/
    ├── __init__.py
    ├── agent.py      # BudgeteerAgent — ReAct agent + intent extractor
    ├── tools.py      # 5 LangChain Tools
    ├── optimizer.py  # DP Knapsack + scoring + random baseline
    └── state.py      # BudgeteerState — session memory
```

---

## วิธีติดตั้งและรัน

### 1. ติดตั้ง dependencies

```bash
pip install -r requirements.txt
```

### 2. ตั้งค่า API Key

**วิธีที่ 1 — ไฟล์ .env**
```bash
cp .env.example .env
# แก้ไข .env ใส่ key จริง
```

```python
# เพิ่มบรรทัดนี้ใน app.py หรือ terminal ก่อนรัน
from dotenv import load_dotenv
load_dotenv()
```

**วิธีที่ 2 — Environment variable**
```powershell
$env:OPENAI_API_KEY = "sk-..."
```

**วิธีที่ 3 — ใส่ใน Streamlit sidebar** (ไม่ต้องแก้ไฟล์)

### 3. รัน Streamlit

```bash
streamlit run app.py
```

เปิด browser ที่ `http://localhost:8501`

---

## Agentic AI Architecture

### ทำไมถึงเป็น Agent จริง (ไม่ใช่แค่ Function Calling)

| Feature | Function Calling ธรรมดา | Sushi-Budgeteer Agent |
|---------|------------------------|----------------------|
| Flow | Fixed pipeline | LLM ตัดสินใจเองทุกขั้น |
| Tool selection | เรียกตามลำดับตายตัว | เลือกตาม context + reason |
| Error handling | ไม่มี retry logic | verify → ปรับ param → optimize ใหม่ |
| State | ไม่จำ context | จำ budget/allergens ตลอดบทสนทนา |
| Clarification | ไม่ถาม | ถามเมื่อข้อมูลไม่ครบ |

### Decision Flow

```
User Message
    │
    ▼ Intent Extractor (LLM → JSON)
    │ budget / allergens / dislikes / preferences / intent
    │
    ▼ BudgeteerState.update_from_extraction()
    │ จำ context ตลอดบทสนทนา
    │
    ▼ ReAct Agent (LangGraph)
    │
    ├── ไม่มีงบ?  → request_clarification(missing=["budget"])
    ├── ถามเมนู?  → search_menu_items(keyword=...)
    └── optimize? → build_optimal_set(budget, allergens, ...)
                         │
                         ├── _run_filter()  ← allergen hard block
                         ├── score_item()   ← preference + price + diversity
                         └── dp_knapsack()  ← 0/1 DP
                              │
                              ▼ verify_result()  ← ตรวจก่อนตอบเสมอ
                              │
                         Pass → Final Response
                         Fail → ปรับ param → optimize ใหม่
```

---

## Tools

| Tool | หน้าที่ | เรียกเมื่อ |
|------|---------|-----------|
| `search_menu_items` | ค้นหาเมนูตาม keyword/category/ราคา | ผู้ใช้ถามเมนูเฉพาะ |
| `filter_constraints` | กรอง allergen (hard) + dislike (soft) | ก่อน optimize |
| `build_optimal_set` | DP Knapsack จัดชุดที่ score สูงสุด | มีงบ + พร้อม optimize |
| `verify_result` | ตรวจยอด + allergen ก่อนส่งคำตอบ | หลัง build เสมอ |
| `request_clarification` | ถามผู้ใช้เมื่อข้อมูลไม่ครบ | งบไม่มี / ขัดแย้ง |

---

## Scoring Algorithm (DP Value Function)

คะแนนความคุ้มค่าของแต่ละเมนู (0–10 คะแนน):

| มิติ | สูงสุด | วิธีคิด |
|-----|--------|---------|
| Preference Score | 5 | ตรงกับ keyword ที่ผู้ใช้ชอบ |
| Price Efficiency | 3 | ราคา 35–80 บาท ได้คะแนนเต็ม |
| Category Diversity | 2 | หมวดที่ไม่ใช่ปลาดิบล้วน |
| Dislike Penalty | -3 | ถ้าตรง dislike ลดคะแนน |

DP ใช้ 0/1 Knapsack: capacity = budget, value = score, weight = price  
Random baseline ใช้เปรียบเทียบเท่านั้น ไม่ใช่ decision จริง

---

## Allergen Policy

| ประเภท | การจัดการ | ที่มา |
|--------|----------|-------|
| **Allergen** (แพ้) | บล็อกอย่างเด็ดขาด | คอลัมน์ `allergens_verified` |
| **Dislike** (ไม่ชอบ) | ยังเข้า DP แต่ score ต่ำกว่า | keyword matching |

Allergen tags ที่รองรับ: `fish`, `crustacean`, `molluscs`, `egg`, `milk`, `gluten`, `soy`, `sesame`, `pork`

> ⚠️ **Disclaimer:** ข้อมูล allergen มาจาก dataset จำลองเท่านั้น ไม่รับประกันการปนเปื้อนจริงในร้าน  
> กรุณาแจ้งพนักงานโดยตรงก่อนสั่งอาหารหากมีอาการแพ้รุนแรง

---

## ตัวอย่างการใช้งาน

```
ผู้ใช้: จัดเซ็ตงบ 300 บาท แพ้กุ้ง ชอบแซลมอน

Agent: [เรียก build_optimal_set(budget=300, allergens=["crustacean"], preferred_keywords=["แซลมอน"])]
       [เรียก verify_result(...)]
       
       ✅ เซ็ตเมนูแนะนำ (300 บาท → ใช้ 280 บาท / 93.3%)
       
       1. ซูชิแซลมอน         40 บาท  🔴
       2. ซูชิหน้าท้องแซลมอน  60 บาท  ⚪
       ...
```

```
ผู้ใช้: แพ้ปลาด้วยนะ

Agent: [อัปเดต state: allergens += ["fish"]]
       [เรียก build_optimal_set ใหม่ด้วย allergens=["crustacean","fish"]]
       [เรียก verify_result(...)]
       
       ✅ จัดเซ็ตใหม่แล้วโดยหลีกเลี่ยงกุ้ง + ปลาทุกชนิด...
```

---

## Tech Stack

- **LangChain** + **LangGraph** — ReAct Agent framework
- **OpenAI GPT-4o-mini** — LLM สำหรับ reasoning + intent extraction
- **Pandas** — data manipulation
- **Streamlit** — UI
- **Python 3.11+** — runtime
