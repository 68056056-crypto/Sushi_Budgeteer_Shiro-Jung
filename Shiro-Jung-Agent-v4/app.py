"""Streamlit UI for Shiro-Jung — single-page chat with the ReAct agent."""

from __future__ import annotations

import os
import sys

# ป้องกันปัญหาหาโฟลเดอร์ sushi_budgeteer ไม่เจอเมื่อรันบน Streamlit Cloud
sys.path.append(os.path.abspath("."))

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ตั้งค่าหน้าเว็บเป็นคำสั่งแรกสุดของ Streamlit
st.set_page_config(page_title="Shiro-Jung", page_icon="🍣", layout="wide")

st.markdown(
    """
    <style>
    .block-container { padding-top: 2rem; padding-bottom: 3rem; }
    [data-testid="stSidebar"] { border-right: 1px solid rgba(224,67,61,0.15); }
    .sb-banner {
        background: linear-gradient(135deg, #E0433D 0%, #F08A3C 100%);
        color: #FFFFFF;
        padding: 1.25rem 1.5rem;
        border-radius: 14px;
        margin-bottom: 1.5rem;
    }
    .sb-banner h1 { color: #FFFFFF; margin: 0 0 0.25rem 0; font-size: 1.6rem; }
    .sb-banner p { color: #FFF3F0; margin: 0; font-size: 0.95rem; }
    [data-testid="stMetric"] {
        background: #FFF3F0;
        border: 1px solid rgba(224,67,61,0.2);
        border-radius: 10px;
        padding: 0.75rem 1rem;
    }
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
    except Exception as e:
        st.error(f"เกิดข้อผิดพลาดในการโหลด Agent: {e}")
        return None


# ----------------------------------------------------------------------
# ดึง API Key อย่างปลอดภัย (รองรับทั้ง Streamlit Secrets บน Cloud และ .env ในเครื่อง)
# ----------------------------------------------------------------------
st.sidebar.title("🍣 Shiro-Jung")
from sushi_budgeteer.policy import DISCLAIMER
st.warning(DISCLAIMER)
mode = st.sidebar.selectbox("โหมดข้อมูล", ["strict", "simulation"],
    help="strict: ถ้ามีการแพ้ จะใช้เฉพาะเมนูที่มีหลักฐาน allergen ยืนยัน; simulation: ทดลองจาก tags จำลองเท่านั้น")
# Mode is passed per Agent subprocess, not assigned to global os.environ.


api_key = ""
model_name = "gpt-4o-mini"

# 1. ตรวจสอบจาก st.secrets ก่อน (กรณีรันบน Streamlit Cloud)
try:
    if hasattr(st, "secrets"):
        if "OPENAI_API_KEY" in st.secrets:
            api_key = st.secrets["OPENAI_API_KEY"]
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
        except Exception:
            pass
        st.session_state["chat_history"] = [{"role": "assistant", "content": GREETING_MESSAGE}]
        st.rerun()


# ----------------------------------------------------------------------
# Chat page
# ----------------------------------------------------------------------
page_header(
    "🍣", "Chat กับ Shiro-Jung",
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
                for chunk in agent.chat_stream(prompt):
                    full_text += chunk
                    placeholder.markdown(full_text + "▌")
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
    if current_agent.last_policy:
        with st.expander("ผลตรวจนโยบายก่อนตอบ (OPA)"):
            st.json(current_agent.last_policy)
    if current_agent.state.last_result:
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
            with st.expander("รายละเอียดองค์ประกอบคะแนนและ constraints"):
                st.json(evidence)
    if show_dev:
        st.download_button("ดาวน์โหลด trace ของ turn ล่าสุด (ไม่มี prompt หรือ API key)",
            data=__import__('json').dumps(current_agent.run_report(),ensure_ascii=False,indent=2),
            file_name="shiro-turn-trace.json",mime="application/json")
