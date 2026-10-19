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
        return BudgeteerAgent(api_key=api_key, model=model, consumer_flow=True)
    except Exception:
        st.error("เตรียมผู้ช่วยไม่สำเร็จ กรุณาตรวจการตั้งค่าระบบแล้วลองใหม่ครับ")
        return None


# ----------------------------------------------------------------------
# ดึง API Key อย่างปลอดภัย (รองรับทั้ง Streamlit Secrets บน Cloud และ .env ในเครื่อง)
# ----------------------------------------------------------------------
st.sidebar.title("🍣 Shiro-Jung")
from sushi_budgeteer.presentation import ALLERGY_WARNING, MENU_NOTICE
st.info('🍱 บอกงบ จำนวนคน การแพ้ และความชอบพร้อมกันได้เลย แล้วเช็กสรุปเพียงครั้งเดียวก่อนจัดชุด '
        'หากแพ้อาหารรุนแรง กรุณาให้พนักงานยืนยันส่วนผสมก่อนสั่ง')
st.sidebar.caption("จัดมื้ออร่อยให้พอดีงบ 🍣")
# Safety mode is a backend deployment setting, not a second consumer questionnaire.
mode = os.getenv("SUSHI_DATA_MODE", "strict")


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
        if st.session_state["agent"].data_mode != mode:
            st.session_state["agent"].clear_choices()
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
    st.sidebar.subheader("มื้อของคุณ 🍱")
    state = st.session_state["agent"].state
    if state.budget:
        st.sidebar.write(f"งบ {state.budget:,.2f} บาท")
    if state.num_people:
        st.sidebar.write(f"สำหรับ {state.num_people} คน")
    if state.allergens:
        names = st.session_state["agent"]._ALLERGEN_TH
        st.sidebar.write("แพ้อาหาร: " + ", ".join(names.get(a, a) for a in state.allergens))
        st.warning(ALLERGY_WARNING)
    if state.preferred_keywords:
        st.sidebar.write("ชอบ: " + ", ".join(state.preferred_keywords))
    if state.dislikes:
        st.sidebar.write("ไม่ชอบ: " + ", ".join(state.dislikes))
    st.sidebar.caption("จำข้อมูลให้ตลอดบทสนทนานี้ เปลี่ยนเมนูได้โดยไม่ต้องเริ่มใหม่")

    if st.sidebar.button("รีเซ็ตบทสนทนา"):
        st.session_state["agent"].reset_order()
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
    st.error("ผู้ช่วยยังไม่พร้อมให้บริการ กรุณาติดต่อผู้ดูแลร้านหรือลองอีกครั้งภายหลังครับ")
elif "agent" not in st.session_state or st.session_state["agent"] is None:
    st.warning("กำลังเตรียมความพร้อมของระบบ กรุณารอสักครู่...")
else:
    for msg in st.session_state.get("chat_history", []):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    typed_prompt = st.chat_input("เช่น งบ 500 บาท 2 คน หรือ เปลี่ยนเป็นแซลมอน ใช้งบเดิม")
    prompt = st.session_state.pop("pending_message", None) or typed_prompt
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

# Only consumer actions are exposed here. Full traces remain on the backend agent.
if "agent" in st.session_state:
    current_agent = st.session_state["agent"]
    if current_agent.last_options:
        st.caption("เลือกชุดที่ถูกใจ หรือพิมพ์บอกสิ่งที่อยากเปลี่ยนได้เลย")
        columns = st.columns(len(current_agent.last_options))
        for index, (column, option) in enumerate(zip(columns, current_agent.last_options)):
            with column:
                if st.button(f"🍱 เลือกชุดที่ {index + 1} · {option['total_price']:,.2f} บาท",
                             key=f"choose_{index}", disabled=current_agent.confirmed_option==index):
                    answer = current_agent.select_option(index)
                    current_agent.state.add_message("assistant", answer)
                    st.session_state.setdefault("chat_history", []).append(
                        {"role": "assistant", "content": answer})
                    st.rerun()
        st.caption("การเลือกชุดเป็นเพียงสรุปสำหรับแจ้งร้าน ยังไม่มีการส่งคำสั่งซื้อหรือชำระเงิน")
    if current_agent.pending_confirmation:
        allergies=[a for a in current_agent.state.allergens if a not in current_agent.pending_allergy_removals]
        confirm_label="ยืนยันข้อมูลและจัดชุด" if allergies else "ยืนยันว่าไม่แพ้และจัดชุด"
        confirm, edit = st.columns(2)
        for column, label in [(confirm, confirm_label), (edit, "แก้ไขข้อมูล")]:
            with column:
                if st.button(label, key="confirm_order" if column is confirm else "edit_order"):
                    st.session_state["pending_message"] = label
                    st.rerun()

st.caption(MENU_NOTICE)
