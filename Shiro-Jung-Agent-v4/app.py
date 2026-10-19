"""Streamlit UI for Shiro-Jung — single-page chat with the ReAct agent."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# ป้องกันปัญหาหาโฟลเดอร์ sushi_budgeteer ไม่เจอเมื่อรันบน Streamlit Cloud
APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT))

import streamlit as st
from dotenv import load_dotenv

load_dotenv(APP_ROOT / ".env", override=False)

# ตั้งค่าหน้าเว็บเป็นคำสั่งแรกสุดของ Streamlit
st.set_page_config(page_title="Shiro-Jung", page_icon="🍣", layout="wide")

st.markdown(
    """
    <style>
    :root { color-scheme: light; }
    [data-testid="stAppViewContainer"], [data-testid="stHeader"] {
        background: #fffaf3; color: #3d3430;
    }
    .block-container { padding-top: 2rem; padding-bottom: 3rem; max-width: 1100px; }
    [data-testid="stSidebar"] { background: #fff0e5; border-right: 1px solid #f3d8c7; }
    [data-testid="stSidebar"] * { color: #493b35; }
    h1, h2, h3, p, label, [data-testid="stMarkdownContainer"] { color: #493b35; }
    .sb-banner {
        background: linear-gradient(120deg, #ffdfcf, #ffecc1 65%, #e4efd6);
        border: 1px solid #f6c7af; padding: 1.6rem; border-radius: 28px;
        margin-bottom: 1.5rem; box-shadow: 0 8px 24px #ac634510;
    }
    .sb-banner h1 { color: #a64032; margin: 0 0 .6rem; font-size: clamp(1.5rem, 4vw, 2.2rem); }
    .sb-banner p { color: #6e5245; margin: 0; line-height: 1.8; }
    [data-testid="stChatMessage"] { background: #ffffff; border: 1px solid #f1dfd0; border-radius: 20px; }
    [data-testid="stChatInput"] { border-radius: 20px; border: 1px solid #e9bda4; background: #ffffff; }
    [data-testid="stChatInput"] textarea { color: #493b35; background: #ffffff; }
    [data-baseweb="select"] > div { background: #ffffff; color: #493b35; }
    .stButton button { background: #bd493b; color: #ffffff; border: 0; border-radius: 14px; }
    .stButton button p { color: #ffffff; }
    [data-testid="stMetric"] { background: #fff0e5; border-radius: 16px; padding: .8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def page_header(icon: str, title: str, subtitle: str = "") -> None:
    """Consistent colored banner header at the top of the page."""
    subtitle_html = f"<p>{subtitle}</p>" if subtitle else ""
    st.markdown(
        f"""<div class="sb-banner"><h1>{icon} {title}</h1>{subtitle_html}</div>""",
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------
# Cached resources & Agent Loader
# ----------------------------------------------------------------------
def _load_agent(api_key: str, model: str):
    try:
        from sushi_budgeteer.agent import BudgeteerAgent
        return BudgeteerAgent(api_key=api_key, model=model)
    except Exception:
        st.error("เตรียมผู้ช่วยไม่สำเร็จ กรุณาตรวจการตั้งค่าระบบแล้วลองใหม่ครับ")
        return None


# ----------------------------------------------------------------------
# ดึง API Key อย่างปลอดภัย (รองรับทั้ง Streamlit Secrets บน Cloud และ .env ในเครื่อง)
# ----------------------------------------------------------------------
st.sidebar.title("🍣 Shiro-Jung")
from sushi_budgeteer.policy import DISCLAIMER
with st.expander("🍵 ข้อมูลเมนูและข้อควรรู้เรื่องการแพ้อาหาร"):
    st.warning(DISCLAIMER)
st.sidebar.caption("จัดมื้ออร่อยให้พอดีงบ 🍣")
mode = st.sidebar.selectbox("โหมดข้อมูล", ["strict", "simulation"],
    help="strict: ถ้ามีการแพ้ จะใช้เฉพาะเมนูที่มีหลักฐาน allergen ยืนยัน; simulation: ทดลองจาก tags จำลองเท่านั้น")
if mode == "strict":
    st.sidebar.caption("🛡️ หากแจ้งแพ้อาหาร จะเลือกเฉพาะเมนูที่มีหลักฐานสารก่อภูมิแพ้ยืนยันจากร้าน")
else:
    st.sidebar.warning("โหมดทดลองใช้ข้อมูลจำลอง ไม่ใช้รับรองความปลอดภัยสำหรับผู้แพ้อาหาร")
# Mode is passed per Agent subprocess, not assigned to global os.environ.


api_key = ""
model_name = "gpt-4o-mini"

# 1. ตรวจสอบจาก st.secrets ก่อน (กรณีรันบน Streamlit Cloud)
try:
    if hasattr(st, "secrets"):
        if "OPENAI_API_KEY" in st.secrets:
            api_key = st.secrets["OPENAI_API_KEY"]
        if not api_key and "SUSHI_OPENAI_API_KEY" in st.secrets:
            api_key = st.secrets["SUSHI_OPENAI_API_KEY"]
        if "OPENAI_MODEL" in st.secrets:
            model_name = st.secrets["OPENAI_MODEL"]
except Exception:
    pass

# 2. ถ้าไม่มีใน st.secrets ให้ดึงจาก Environment Variable หรือไฟล์ .env
if not api_key:
    api_key = os.getenv("OPENAI_API_KEY", "") or os.getenv("SUSHI_OPENAI_API_KEY", "")
if not model_name or model_name == "gpt-4o-mini":
    model_name = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


# ----------------------------------------------------------------------
# Sidebar — จัดการสถานะบทสนทนา
# ----------------------------------------------------------------------
GREETING_MESSAGE = (
    "สวัสดีครับ ผมชื่อ Shiro-Jung มีหน้าที่เป็นผู้ช่วยจัดงบประมาณเมนูซูชิให้คุณครับ "
    "ลองบอกงบประมาณและจำนวนคนที่รับประทานได้เลยครับ"
)

if api_key:
    # Switching strict/simulation keeps the conversation: only the data mode of the next turn changes.
    if "agent" in st.session_state and st.session_state.get("_agent_key", (None, None, None))[:2] == (api_key, model_name):
        st.session_state["agent"].data_mode = mode
        st.session_state["_agent_key"] = (api_key, model_name, mode)
    if "agent" not in st.session_state or st.session_state.get("_agent_key") != (api_key, model_name, mode):
        loaded_agent = _load_agent(api_key, model_name)
        if loaded_agent:
            st.session_state["agent"] = loaded_agent
            st.session_state["_agent_key"] = (api_key, model_name, mode)
            loaded_agent.data_mode = mode
            if not st.session_state.get("chat_history"):
                st.session_state["chat_history"] = [{"role": "assistant", "content": GREETING_MESSAGE}]

if "agent" in st.session_state and st.session_state["agent"] is not None:
    st.sidebar.divider()
    st.sidebar.subheader("สถานะบทสนทนาปัจจุบัน")
    try:
        st.sidebar.text(st.session_state["agent"].state.to_summary())
    except Exception:
        pass

    if st.sidebar.button("รีเซ็ตบทสนทนา"):
        try:
            st.session_state["agent"].state.reset()
            st.session_state["agent"].last_policy = None
            st.session_state["agent"].last_trace = []
            st.session_state["agent"].last_run = {}
        except Exception:
            pass
        st.session_state["chat_history"] = [{"role": "assistant", "content": GREETING_MESSAGE}]
        st.rerun()


# ----------------------------------------------------------------------
# Chat page
# ----------------------------------------------------------------------
page_header(
    "🍣", "Shiro-Jung • มื้ออร่อยในงบของคุณ",
    "พิมพ์งบประมาณ อาการแพ้อาหาร และความชอบของคุณ แล้วให้ Shiro-Jung จัดชุดเมนูที่คุ้มค่าที่สุดให้ครับ",
)

if not api_key:
    st.error("⚠️ ไม่พบ OPENAI_API_KEY — กรุณาใส่ในไฟล์ .env (หากรันในเครื่อง) หรือตั้งค่าใน Settings -> Secrets บน Streamlit Cloud")
elif "agent" not in st.session_state or st.session_state["agent"] is None:
    st.warning("กำลังเตรียมความพร้อมของระบบ กรุณารอสักครู่...")
else:
    for msg in st.session_state.get("chat_history", []):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    prompt = st.chat_input("เช่น: จัดเซ็ตงบ 300 บาท แพ้กุ้ง ชอบแซลมอน")
    if prompt:
        st.session_state["chat_history"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        agent = st.session_state["agent"]
        with st.chat_message("assistant"):
            placeholder = st.empty()
            full_text = ""
            try:
                with st.spinner("🍣 กำลังอ่านความต้องการ จัดเมนู และตรวจเงื่อนไขให้ครับ…"):
                    full_text = agent.chat(prompt)
                placeholder.markdown(full_text)
            except Exception:
                full_text = "ระบบขัดข้อง ยังไม่มีคำแนะนำที่ผ่านตรวจสอบ กรุณาลองใหม่ครับ"
                placeholder.markdown(full_text)

        st.session_state["chat_history"].append({"role": "assistant", "content": full_text})
        st.rerun()
# Developer details are hidden by default; turn on in the sidebar for demos.
show_dev = st.sidebar.toggle("แสดงข้อมูลสำหรับผู้พัฒนา (MCP trace)", value=False)
if "agent" in st.session_state and show_dev:
    with st.expander("MCP tool trace ของ turn ล่าสุด (ไม่มี API key)"):
        st.json(st.session_state["agent"].last_trace)

if "agent" in st.session_state:
    current_agent=st.session_state["agent"]
    if current_agent.last_policy and show_dev:
        with st.expander("ผลตรวจนโยบายก่อนตอบ (OPA)"):
            st.json(current_agent.last_policy)
    if (current_agent.state.last_result and current_agent.last_policy
            and current_agent.last_policy.get("allow")):
        result=current_agent.state.last_result
        evidence=result.get('explanation',{})
        with st.expander("เหตุผลที่เลือกเมนูและที่มาของข้อมูล", expanded=True):
            st.caption("คำนวณจากฐานข้อมูลและสูตรคะแนน ไม่ใช่คำอธิบายที่ LLM แต่งขึ้น")
            st.write(f"คะแนนอาหารรวม: {evidence.get('food_score_total')} | งบคงเหลือ: {evidence.get('budget_remaining')} บาท")
            st.dataframe([{'เมนู':x['name'],'จำนวน':x['quantity'],'ราคาต่อหน่วย':x['unit_price'],
                'ยอด':x['subtotal'],'เหตุผล':x['selection_method'],
                'สถานะราคา':x['price_status'],'สถานะ allergen':x['allergen_status'],
                'แหล่งราคา':x['source_url'] or 'ยังไม่มีหลักฐาน','แหล่ง allergen':x['allergen_source_url'] or 'ยังไม่มีหลักฐาน',
                'วันที่ตรวจ':x['checked_at'] or 'ยังไม่ตรวจ'} for x in evidence.get('items',[])],hide_index=True)
            if show_dev:
                with st.expander("รายละเอียดองค์ประกอบคะแนนและ constraints"):
                    st.json(evidence)
    if show_dev:
        st.download_button("ดาวน์โหลด trace ของ turn ล่าสุด (ไม่มี prompt หรือ API key)",
            data=__import__('json').dumps(current_agent.run_report(),ensure_ascii=False,indent=2),
            file_name="shiro-turn-trace.json",mime="application/json")
