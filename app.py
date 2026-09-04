"""
app.py — Sushi-Budgeteer Streamlit UI

หน้าหลัก:
  🍣 Chat      — สนทนากับ Agent จัดเซ็ตเมนู
  📊 Compare   — เปรียบเทียบ DP vs Random baseline
  📋 Menu      — ดูเมนูทั้งหมดในฐานข้อมูล
  ℹ️  About    — อธิบาย architecture ของระบบ

วิธีรัน:
  streamlit run app.py
"""

import os
import sys

import pandas as pd
import streamlit as st

# ---------------------------------------------------------------------------
# Path setup — ให้ import module ใน sushi_budgeteer/ ได้
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
PKG_PATH = os.path.join(ROOT, "sushi_budgeteer")
sys.path.insert(0, PKG_PATH)
sys.path.insert(0, ROOT)

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="🍣 Sushi-Budgeteer",
    page_icon="🍣",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Load .env if present (optional — user can also set via sidebar or env var)
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
except ImportError:
    pass  # python-dotenv not installed — use env var or sidebar input

# ---------------------------------------------------------------------------
# Lazy imports (หลัง path setup)
# ---------------------------------------------------------------------------
@st.cache_resource(show_spinner="กำลังโหลด Agent...")
def load_agent():
    from agent import BudgeteerAgent
    return BudgeteerAgent()


@st.cache_data(show_spinner=False)
def load_menu_df():
    csv_path = os.path.join(ROOT, "sushiro_menu_dataset.csv")
    df = pd.read_csv(csv_path)
    return df


# ---------------------------------------------------------------------------
# Custom CSS
# ---------------------------------------------------------------------------
st.markdown(
    """
    <style>
    .main-title { font-size: 2.2rem; font-weight: 700; color: #d32f2f; }
    .subtitle   { font-size: 1rem; color: #666; margin-bottom: 1rem; }
    .stat-box   {
        background: #fff8f8; border: 1px solid #ffcdd2; border-radius: 8px;
        padding: 12px 16px; margin: 4px 0;
    }
    .stat-label { font-size: 0.78rem; color: #999; }
    .stat-value { font-size: 1.1rem; font-weight: 600; color: #c62828; }
    .allergen-badge {
        display: inline-block; background: #fce4ec; color: #c62828;
        border-radius: 12px; padding: 2px 10px; font-size: 0.75rem;
        margin: 2px;
    }
    .tool-card {
        background: #f8f9fa; border-left: 3px solid #d32f2f;
        border-radius: 4px; padding: 8px 12px; margin: 6px 0;
        font-size: 0.88rem;
    }
    .dp-winner { background: #e8f5e9; border: 1px solid #a5d6a7; border-radius: 8px; padding: 12px; }
    .rand-loser { background: #fff3e0; border: 1px solid #ffcc80; border-radius: 8px; padding: 12px; }
    .disclaimer {
        background: #fff8e1; border: 1px solid #ffe082; border-radius: 6px;
        padding: 10px 14px; font-size: 0.82rem; color: #5d4037;
    }
    .rag-card {
        background: #f3f0ff; border: 1px solid #ce93d8; border-radius: 8px;
        padding: 10px 14px; margin: 6px 0;
    }
    .rag-badge {
        display: inline-block; background: #7b1fa2; color: white;
        border-radius: 12px; padding: 2px 10px; font-size: 0.72rem;
        margin-right: 6px; vertical-align: middle;
    }
    .sim-bar-bg {
        background: #e0d7f5; border-radius: 4px; height: 6px;
        display: inline-block; width: 80px; vertical-align: middle;
    }
    .sim-bar-fill {
        background: #7b1fa2; border-radius: 4px; height: 6px; display: block;
    }
    div[data-testid="stChatMessage"] { padding: 0.5rem 0; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Sidebar — navigation + state display
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown('<div class="main-title">🍣 Sushi-Budgeteer</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">AI Agent จัดเซ็ตเมนูซูชิตามงบประมาณ</div>', unsafe_allow_html=True)

    st.divider()

    page = st.radio(
        "เลือกหน้า",
        ["🍣 Chat กับ Agent", "� RAG Search", "�📊 DP vs Random", "📋 ดูเมนูทั้งหมด", "ℹ️ Architecture"],
        label_visibility="collapsed",
    )

    st.divider()

    # API Key input
    api_key_input = st.text_input(
        "🔑 OpenAI API Key",
        type="password",
        placeholder="sk-...",
        help="ใส่ key ของคุณที่นี่ หรือ set OPENAI_API_KEY environment variable",
    )
    if api_key_input:
        os.environ["OPENAI_API_KEY"] = api_key_input

    st.divider()

    # State display (ถ้า agent โหลดแล้ว)
    if "agent" in st.session_state:
        agent = st.session_state["agent"]
        st.markdown("**📌 Session State**")
        st.text(agent.get_state_summary())

        if st.button("🔄 Reset", use_container_width=True):
            agent.chat("reset")
            st.session_state["messages"] = []
            st.rerun()


# ---------------------------------------------------------------------------
# Helper: ensure API key
# ---------------------------------------------------------------------------
def _check_api_key() -> bool:
    if not os.environ.get("OPENAI_API_KEY"):
        st.warning("กรุณาใส่ OpenAI API Key ที่ sidebar ก่อนใช้งาน")
        return False
    return True


# ---------------------------------------------------------------------------
# Page 1 — Chat
# ---------------------------------------------------------------------------
if page == "🍣 Chat กับ Agent":
    st.header("🍣 สนทนากับ Sushi-Budgeteer Agent")

    col1, col2 = st.columns([7, 3])

    with col2:
        with st.expander("💡 ตัวอย่างการใช้งาน", expanded=True):
            examples = [
                "จัดเซ็ตงบ 300 บาท ชอบแซลมอน",
                "งบ 200 บาท แพ้กุ้ง ไม่กินหอย",
                "งบ 500 บาท อยากได้อย่างน้อย 8 จาน",
                "มีเมนูอะไรราคาไม่เกิน 60 บาทบ้าง",
                "เปรียบเทียบ DP กับ random ให้ดูหน่อย",
                "แพ้ปลาด้วย ช่วยจัดใหม่",
            ]
            for ex in examples:
                if st.button(ex, key=f"ex_{ex}", use_container_width=True):
                    st.session_state["pending_input"] = ex

        with st.expander("🔍 ตัวอย่าง RAG Search"):
            rag_examples = [
                "อยากได้อะไรมันๆ ละลายในปาก",
                "ของหวานเบาๆ ไม่หวานมาก",
                "อาหารทอดกรอบๆ",
                "จัดงบ 400 บาท อยากได้รสเข้มข้น มีทั้งปลาและของทอด",
                "เมนูที่เหมาะกับคนที่แพ้กลูเตน",
            ]
            for ex in rag_examples:
                if st.button(ex, key=f"rag_{ex}", use_container_width=True):
                    st.session_state["pending_input"] = ex

        with st.expander("🚫 Allergen Tags"):
            tags = {
                "fish": "ปลา", "crustacean": "กุ้ง/ปู",
                "molluscs": "หอย/หมึก", "egg": "ไข่",
                "milk": "นม", "gluten": "กลูเตน/แป้งสาลี",
                "soy": "ถั่วเหลือง", "sesame": "งา", "pork": "หมู",
            }
            for tag, label in tags.items():
                st.markdown(
                    f'<span class="allergen-badge">{tag}</span> {label}',
                    unsafe_allow_html=True,
                )

    with col1:
        if not _check_api_key():
            st.stop()

        # Init agent
        if "agent" not in st.session_state:
            try:
                st.session_state["agent"] = load_agent()
                st.session_state["messages"] = []
            except Exception as e:
                st.error(f"โหลด Agent ไม่สำเร็จ: {e}")
                st.stop()

        agent = st.session_state["agent"]
        messages = st.session_state.get("messages", [])

        # Render conversation history
        chat_container = st.container()
        with chat_container:
            if not messages:
                st.info(
                    "👋 สวัสดีครับ! บอกงบประมาณและความต้องการได้เลย\n\n"
                    "เช่น: **\"จัดเซ็ตงบ 300 บาท แพ้กุ้ง ชอบแซลมอน\"**"
                )
            for msg in messages:
                role = msg["role"]
                content = msg["content"]
                with st.chat_message(role, avatar="🍣" if role == "assistant" else "👤"):
                    st.markdown(content)

        # Handle pre-filled input from example buttons
        pending = st.session_state.pop("pending_input", None)

        user_input = st.chat_input("พิมพ์ข้อความของคุณ...", key="chat_input")
        if pending:
            user_input = pending

        if user_input:
            # Show user message immediately
            messages.append({"role": "user", "content": user_input})
            with chat_container:
                with st.chat_message("user", avatar="👤"):
                    st.markdown(user_input)

            # Get agent response with streaming
            with chat_container:
                with st.chat_message("assistant", avatar="🍣"):
                    response_placeholder = st.empty()
                    full_response = ""
                    try:
                        for token in agent.chat_stream(user_input):
                            full_response += token
                            response_placeholder.markdown(full_response + "▌")
                        response_placeholder.markdown(full_response)
                    except Exception as e:
                        full_response = f"❌ เกิดข้อผิดพลาด: {str(e)}"
                        response_placeholder.error(full_response)

            messages.append({"role": "assistant", "content": full_response})
            st.session_state["messages"] = messages
            st.rerun()


# ---------------------------------------------------------------------------
# Page 2 — RAG Search (Semantic)
# ---------------------------------------------------------------------------
elif page == "🔍 RAG Search":
    st.header("🔍 RAG Semantic Search")
    st.markdown(
        "ค้นหาเมนูด้วย **ความหมาย** ผ่าน FAISS Vector Store — "
        "ไม่ต้องรู้ชื่อเมนูตรงๆ แค่อธิบายรสชาติหรือความต้องการ"
    )

    if not _check_api_key():
        st.stop()

    # ---- Build index section ----
    with st.expander("⚙️ จัดการ Vector Index", expanded=False):
        st.markdown(
            "Index จะถูกสร้างอัตโนมัติครั้งแรก และ save ไว้ใน `sushi_budgeteer/faiss_index/`"
        )
        col_idx1, col_idx2 = st.columns(2)
        if col_idx1.button("🔨 Build / Rebuild Index", use_container_width=True):
            with st.spinner("กำลัง embed เมนูทั้งหมด..."):
                try:
                    from rag import rebuild_index
                    rebuild_index()
                    st.success("สร้าง FAISS index สำเร็จ!")
                except Exception as e:
                    st.error(f"Error: {e}")

        import os as _os
        index_path = _os.path.join(PKG_PATH, "faiss_index")
        if _os.path.exists(index_path):
            col_idx2.success("✅ Index มีอยู่แล้ว")
        else:
            col_idx2.warning("⚠️ ยังไม่มี index — กด Build ก่อน")

    st.divider()

    # ---- Search form ----
    with st.form("rag_search_form"):
        query_input = st.text_input(
            "🔍 ค้นหาด้วยความหมาย",
            placeholder="เช่น: อะไรมันๆ ละลายในปาก, ของหวานเบาๆ, อาหารทอดกรอบ",
        )
        scol1, scol2, scol3 = st.columns(3)
        top_k = scol1.slider("จำนวนผลลัพธ์", 1, 10, 5)
        max_price_rag = scol2.number_input("ราคาสูงสุด (0=ไม่จำกัด)", 0, 500, 0, step=10)
        allergen_rag = scol3.multiselect(
            "กรอง allergen",
            ["fish", "crustacean", "molluscs", "egg", "milk", "gluten", "soy", "sesame", "pork"],
        )
        submitted = st.form_submit_button("🔍 ค้นหา", type="primary", use_container_width=True)

    if submitted and query_input:
        with st.spinner("กำลังค้นหาด้วย semantic similarity..."):
            try:
                from rag import semantic_search_menu
                result = semantic_search_menu.invoke({
                    "query": query_input,
                    "top_k": top_k,
                    "allergens_exclude": allergen_rag,
                    "max_price": max_price_rag,
                })
            except Exception as e:
                st.error(f"ค้นหาไม่สำเร็จ: {e}")
                result = None

        if result:
            items = result.get("results", [])
            if not items:
                st.warning("ไม่พบเมนูที่ตรงกับความต้องการ ลองปรับ query หรือเพิ่ม top_k")
            else:
                st.success(f"พบ **{len(items)} เมนู** ที่ตรงกับ \"{query_input}\"")
                st.caption("เรียงตาม similarity score (สูง = ใกล้เคียงกว่า)")

                for i, item in enumerate(items, 1):
                    sim = item.get("similarity_score", 0)
                    sim_pct = int(sim * 100)
                    bar_width = max(4, int(sim * 80))

                    with st.container():
                        st.markdown(
                            f'<div class="rag-card">'
                            f'<span class="rag-badge">#{i}</span>'
                            f'<b>{item["name_th"]}</b> '
                            f'<span style="color:#666;font-size:0.85rem">({item["name_en"]})</span>'
                            f'<br>'
                            f'<span style="color:#7b1fa2;font-size:0.8rem">Similarity: {sim_pct}% &nbsp;</span>'
                            f'<span class="sim-bar-bg"><span class="sim-bar-fill" style="width:{bar_width}px"></span></span>'
                            f'<br>'
                            f'<span style="font-size:0.82rem;color:#444">'
                            f'🏷️ {item["category"]} &nbsp;|&nbsp; '
                            f'💰 {item["price_baht"]} บาท &nbsp;|&nbsp; '
                            f'⚠️ {item["allergens_verified"] or "ไม่มี allergen"}'
                            f'</span>'
                            f'<br><span style="font-size:0.8rem;color:#666">{item["description_th"]}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

                st.divider()

                # ---- RAG Augmented Build ----
                st.subheader("🧮 จัดเซ็ตจาก RAG Candidates")
                st.caption("ใช้ผล semantic search เป็น candidate pool แล้วส่งเข้า DP Knapsack")

                with st.form("rag_build_form"):
                    rb_col1, rb_col2 = st.columns(2)
                    rag_budget = rb_col1.number_input("งบประมาณ (บาท)", 40, 2000, 300, step=10)
                    rag_min_items = rb_col2.number_input("จำนวนจานขั้นต่ำ", 1, 20, 1)
                    build_submitted = st.form_submit_button(
                        "▶ จัดเซ็ตด้วย RAG + DP", type="primary", use_container_width=True
                    )

                if build_submitted:
                    with st.spinner("RAG → filter → score → DP Knapsack..."):
                        try:
                            from rag import rag_augmented_build
                            build_result = rag_augmented_build.invoke({
                                "budget": rag_budget,
                                "preference_description": query_input,
                                "allergens": allergen_rag,
                                "dislikes": [],
                                "min_items": rag_min_items,
                                "max_items": 20,
                            })
                        except Exception as e:
                            st.error(f"จัดเซ็ตไม่สำเร็จ: {e}")
                            build_result = None

                    if build_result:
                        if build_result.get("feasible"):
                            bp1, bp2, bp3, bp4 = st.columns(4)
                            bp1.metric("จำนวนจาน", build_result["item_count"])
                            bp2.metric("ยอดรวม", f'{build_result["total_price"]} ฿')
                            bp3.metric("ใช้งบ", f'{build_result["budget_utilization_pct"]}%')
                            bp4.metric("RAG Candidates", build_result.get("retrieved_candidates", "-"))

                            st.markdown(
                                f'<span class="rag-badge">RAG + DP</span> '
                                f'Source: `{build_result.get("retrieval_source","rag")}`',
                                unsafe_allow_html=True,
                            )

                            result_df = pd.DataFrame(build_result["selected_items"])[
                                ["name_th", "category", "price_baht", "allergens_verified"]
                            ].rename(columns={
                                "name_th": "เมนู", "category": "หมวด",
                                "price_baht": "ราคา", "allergens_verified": "Allergens",
                            })
                            st.dataframe(result_df, hide_index=True, use_container_width=True)

                            st.markdown(
                                '<div class="disclaimer">⚠️ ข้อมูล allergen มาจาก dataset จำลองเท่านั้น '
                                'ไม่รับประกันการปนเปื้อนจริงในร้าน</div>',
                                unsafe_allow_html=True,
                            )
                        else:
                            st.warning(f"จัดเซ็ตไม่สำเร็จ: {build_result.get('message','')}")

    st.divider()

    # ---- RAG Architecture Explanation ----
    with st.expander("📖 RAG ทำงานอย่างไรในระบบนี้", expanded=False):
        st.markdown("""
        ```
        User Query: "อยากได้อะไรมันๆ ละลายในปาก"
              │
              ▼ OpenAI text-embedding-3-small
        Query Vector [0.12, -0.34, ...]
              │
              ▼ FAISS cosine similarity search
        Top-K Menu Documents
        ┌──────────────────────────────────────────────┐
        │ S015 โอโทโร่   sim=0.87  "ท้องทูน่าไขมันสูง" │
        │ S007 อูนิ       sim=0.82  "ครีมมี่เข้มข้น"    │
        │ S016 ท้องแซลมอน sim=0.79  "มันฉ่ำ"            │
        └──────────────────────────────────────────────┘
              │
              ▼ allergen filter (hard block)
              ▼ score_item() + similarity_bonus
              ▼ dp_knapsack(budget)
        Optimal Set → verify_result → Response
        ```

        **Document ที่ embed** = `ชื่อ + description_th + keywords + category + ราคา`

        **Similarity score** แปลงจาก FAISS L2 distance → `1 / (1 + distance)` (0–1)

        **Similarity bonus** = `similarity_score × 2.0` บวกเพิ่มใน DP value function
        """)


# ---------------------------------------------------------------------------
# Page 3 — DP vs Random Comparison
# ---------------------------------------------------------------------------
elif page == "📊 DP vs Random":
    st.header("📊 เปรียบเทียบ DP Knapsack vs Random Baseline")

    st.markdown(
        """
        หน้านี้แสดงให้เห็นว่า **Dynamic Programming** จัดเซ็ตได้ดีกว่า **Random** อย่างไร
        โดยทดสอบกับชุดค่าต่างๆ เพื่อยืนยัน algorithm

        > Random ใช้เป็น **baseline เปรียบเทียบเท่านั้น** — ไม่ใช่ decision จริงของระบบ
        """
    )

    col_a, col_b, col_c = st.columns(3)
    budget_test = col_a.number_input("งบทดสอบ (บาท)", min_value=40, max_value=2000, value=300, step=10)
    allergen_test = col_b.multiselect(
        "กรอง allergen",
        ["fish", "crustacean", "molluscs", "egg", "milk", "gluten", "soy", "sesame", "pork"],
        default=[],
    )
    pref_test = col_c.text_input("Keyword ที่ชอบ (คั่นด้วย ,)", placeholder="แซลมอน,กุ้ง")

    run_compare = st.button("▶ เรียกใช้การเปรียบเทียบ", type="primary", use_container_width=True)

    if run_compare:
        import pandas as pd
        from optimizer import dp_knapsack, random_baseline, score_item, compare_dp_vs_random

        # Load + filter data
        df = load_menu_df()
        df["allergen_set"] = df["allergens_verified"].apply(
            lambda x: set(str(x).lower().split(";")) - {""} - {"nan"}
            if pd.notna(x) and str(x).strip() else set()
        )

        # Filter allergens
        if allergen_test:
            df = df[~df["allergen_set"].apply(lambda s: bool(s & set(allergen_test)))]

        # Score items
        prefs = [p.strip().lower() for p in pref_test.split(",") if p.strip()]
        items_with_score = []
        for _, row in df.iterrows():
            s = score_item(row=row, preferred_keywords=prefs, budget=budget_test, is_disliked=False)
            items_with_score.append({**row.to_dict(), "score": s})

        if not items_with_score:
            st.error("ไม่มีเมนูที่ผ่านเงื่อนไข allergen")
        else:
            result = compare_dp_vs_random(
                items=items_with_score,
                budget=budget_test,
                max_items=20,
            )
            dp_r = result["dp"]
            rand_r = result["random"]
            imp = result["improvement"]

            # --- KPI row ---
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("DP Total Score", f"{dp_r['total_score']:.2f}")
            k2.metric("Random Total Score", f"{rand_r['total_score']:.2f}")
            k3.metric(
                "Score Improvement",
                f"+{imp['score_gain']:.2f}",
                delta=f"+{imp['score_gain_pct']:.1f}%",
            )
            k4.metric(
                "Budget Utilization (DP)",
                f"{round(dp_r['total_price']/budget_test*100, 1)}%",
                delta=f"{dp_r['total_price']} บาท",
            )

            st.divider()

            col_dp, col_rand = st.columns(2)

            with col_dp:
                st.markdown('<div class="dp-winner">', unsafe_allow_html=True)
                st.markdown(f"### 🏆 DP Knapsack — {dp_r['item_count']} จาน / {dp_r['total_price']} บาท")
                dp_table = pd.DataFrame(dp_r["selected_items"])[
                    ["name_th", "category", "price_baht"]
                ].rename(columns={"name_th": "เมนู", "category": "หมวด", "price_baht": "ราคา"})
                st.dataframe(dp_table, hide_index=True, use_container_width=True)
                st.markdown("</div>", unsafe_allow_html=True)

            with col_rand:
                st.markdown('<div class="rand-loser">', unsafe_allow_html=True)
                st.markdown(f"### 🎲 Random Baseline — {rand_r['item_count']} จาน / {rand_r['total_price']} บาท")
                if rand_r["selected_items"]:
                    rand_table = pd.DataFrame(rand_r["selected_items"])[
                        ["name_th", "category", "price_baht"]
                    ].rename(columns={"name_th": "เมนู", "category": "หมวด", "price_baht": "ราคา"})
                    st.dataframe(rand_table, hide_index=True, use_container_width=True)
                else:
                    st.info("Random ไม่สามารถเลือกได้")
                st.markdown("</div>", unsafe_allow_html=True)

            st.divider()

            # --- Score breakdown bar chart ---
            st.subheader("Score Breakdown ของเมนูที่ DP เลือก")
            score_data = []
            for item in items_with_score:
                if any(i.get("item_id") == item.get("item_id") for i in dp_r["selected_items"]):
                    score_data.append({
                        "เมนู": item["name_th"],
                        "Score": item["score"],
                        "ราคา": item["price_baht"],
                    })
            if score_data:
                score_df = pd.DataFrame(score_data).sort_values("Score", ascending=True)
                st.bar_chart(score_df.set_index("เมนู")["Score"])

            # Run multiple seeds comparison
            st.subheader("เปรียบเทียบ Random หลาย seed (DP คงที่)")
            seed_results = []
            for seed in range(10):
                r = random_baseline(items=items_with_score, budget=budget_test, seed=seed)
                seed_results.append({
                    "Seed": seed,
                    "Random Score": r["total_score"],
                    "Random Items": r["item_count"],
                    "Random Price": r["total_price"],
                    "DP Score": dp_r["total_score"],
                })
            seed_df = pd.DataFrame(seed_results)
            st.dataframe(seed_df, hide_index=True, use_container_width=True)

            avg_rand = seed_df["Random Score"].mean()
            st.info(
                f"DP Score: **{dp_r['total_score']:.2f}** | "
                f"Average Random Score (10 seeds): **{avg_rand:.2f}** | "
                f"DP ดีกว่าเฉลี่ย **{((dp_r['total_score']-avg_rand)/max(avg_rand,0.001)*100):.1f}%**"
            )


# ---------------------------------------------------------------------------
# Page 4 — Menu Browser
# ---------------------------------------------------------------------------
elif page == "📋 ดูเมนูทั้งหมด":
    st.header("📋 เมนูทั้งหมดในฐานข้อมูล Sushiro")

    df = load_menu_df()

    # Filters
    fcol1, fcol2, fcol3 = st.columns(3)
    cat_filter = fcol1.multiselect("หมวดหมู่", sorted(df["category"].unique()))
    price_max = fcol2.slider("ราคาสูงสุด (บาท)", 0, 200, 200, step=5)
    allergen_filter = fcol3.multiselect(
        "ซ่อนเมนูที่มี allergen",
        ["fish", "crustacean", "molluscs", "egg", "milk", "gluten", "soy", "sesame", "pork"],
    )

    display_df = df.copy()

    if cat_filter:
        display_df = display_df[display_df["category"].isin(cat_filter)]

    if price_max < 200:
        display_df = display_df[display_df["price_baht"] <= price_max]

    if allergen_filter:
        display_df["allergen_set_tmp"] = display_df["allergens_verified"].apply(
            lambda x: set(str(x).lower().split(";")) - {""} - {"nan"}
            if pd.notna(x) and str(x).strip() else set()
        )
        display_df = display_df[
            ~display_df["allergen_set_tmp"].apply(lambda s: bool(s & set(allergen_filter)))
        ].drop(columns=["allergen_set_tmp"])

    st.caption(f"แสดง {len(display_df)} รายการ จากทั้งหมด {len(df)} รายการ")

    # Color-code by plate color
    plate_colors = {
        "แดง": "🔴", "เงิน": "⚪", "ทอง": "🟡",
        "ดำ": "⚫", "ฟรี": "🆓", "เซ็ตพิเศษ": "🎁", "เมนูเครื่องดื่ม": "🥤"
    }

    show_df = display_df[["item_id", "name_th", "name_en", "category", "plate_color", "price_baht", "allergens_verified"]].copy()
    show_df["จาน"] = show_df["plate_color"].map(lambda c: plate_colors.get(c, "🍽️"))
    show_df = show_df.rename(columns={
        "item_id": "ID", "name_th": "ชื่อไทย", "name_en": "ชื่ออังกฤษ",
        "category": "หมวด", "plate_color": "สีจาน",
        "price_baht": "ราคา (บาท)", "allergens_verified": "Allergens",
    })

    st.dataframe(
        show_df[["จาน", "ID", "ชื่อไทย", "ชื่ออังกฤษ", "หมวด", "ราคา (บาท)", "Allergens"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "ราคา (บาท)": st.column_config.NumberColumn(format="%d ฿"),
        },
    )

    # Category breakdown
    st.subheader("สรุปตามหมวดหมู่")
    cat_summary = df.groupby("category").agg(
        จำนวน=("item_id", "count"),
        ราคาเฉลี่ย=("price_baht", "mean"),
        ราคาต่ำสุด=("price_baht", "min"),
        ราคาสูงสุด=("price_baht", "max"),
    ).reset_index()
    cat_summary["ราคาเฉลี่ย"] = cat_summary["ราคาเฉลี่ย"].round(0).astype(int)
    st.dataframe(cat_summary, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Page 5 — Architecture
# ---------------------------------------------------------------------------
elif page == "ℹ️ Architecture":
    st.header("ℹ️ Sushi-Budgeteer: Agentic AI Architecture")

    st.markdown(
        """
        ## ทำไมถึงเป็น Agentic AI จริง (ไม่ใช่แค่ Function Calling)

        ระบบนี้ต่างจาก fixed pipeline ตรงที่ **LLM ตัดสินใจเองว่าจะเรียก Tool ไหน
        ในลำดับใด** โดยอิงจากบริบทของการสนทนา — ไม่ใช่ flow ตายตัว

        ---

        ## Agent Decision Flow
        ```
        User Message
             │
             ▼
        ┌─────────────────────────────────────┐
        │  Intent Extractor (LLM)             │
        │  → budget / allergens / preferences │
        │  → intent: optimize/search/clarify  │
        └────────────────┬────────────────────┘
                         │
                         ▼
        ┌─────────────────────────────────────┐
        │  BudgeteerState (Session Memory)    │
        │  → จำ budget, allergens, dislikes   │
        │  → ตลอดการสนทนา (ไม่รีเซ็ตทุก turn)│
        └────────────────┬────────────────────┘
                         │
                         ▼
        ┌─────────────────────────────────────┐
        │  ReAct Agent (LangGraph)            │
        │  Reason → Act → Observe → Repeat   │
        └──┬──────────────────────────────────┘
           │
           ├─► ไม่มีงบ?
           │     └─► request_clarification("budget")
           │
           ├─► ถามเมนู?
           │     └─► search_menu_items(keyword)
           │
           ├─► พร้อม optimize?
           │     └─► build_optimal_set(budget, allergens, ...)
           │              │
           │              ▼
           │         filter_constraints (hard/soft)
           │              │
           │              ▼
           │         dp_knapsack (0/1 DP)
           │              │
           │              ▼
           │         verify_result ←── ต้องเรียกทุกครั้ง
           │              │
           │         ┌────┴────┐
           │       Pass      Fail
           │         │        └─► ปรับ parameter → optimize ใหม่
           │         ▼
           └─► Final Response to User
        ```

        ---

        ## Tools และหน้าที่
        """
    )

    tools_info = [
        ("🔍 search_menu_items", "ค้นหาเมนูตาม keyword/category/ราคา", "เมื่อผู้ใช้ถามเมนูเฉพาะ"),
        ("🚫 filter_constraints", "กรอง allergen (hard) และ dislike (soft)", "ก่อน optimize ทุกครั้ง"),
        ("🧮 build_optimal_set", "DP Knapsack จัดชุดที่ score สูงสุด", "เมื่อมีงบและพร้อม optimize"),
        ("✅ verify_result", "ตรวจยอด + allergen ก่อนส่งคำตอบ", "หลัง build_optimal_set เสมอ"),
        ("❓ request_clarification", "ถามผู้ใช้เมื่อข้อมูลไม่ครบ", "งบไม่มี / น้อยเกินไป / ขัดแย้ง"),
    ]

    for name, desc, when in tools_info:
        st.markdown(
            f'<div class="tool-card"><b>{name}</b> — {desc}<br>'
            f'<span style="color:#999">เรียกเมื่อ: {when}</span></div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        ---

        ## Scoring Algorithm (DP Value Function)

        คะแนนความคุ้มค่าของแต่ละเมนู (0–10 คะแนน):

        | มิติ | คะแนนสูงสุด | วิธีคิด |
        |------|------------|---------|
        | Preference Score | 5 | ตรงกับ keyword ที่ผู้ใช้ชอบ |
        | Price Efficiency | 3 | ราคา 35–80 บาท ได้คะแนนเต็ม |
        | Category Diversity | 2 | เมนูที่ไม่ใช่ปลาดิบล้วน |
        | Dislike Penalty | -3 | ถ้าตรง dislike ลดคะแนน |
        | **RAG Similarity Bonus** | **+2** | **similarity_score × 2.0 (เฉพาะ rag_augmented_build)** |

        ---

        ## RAG Architecture

        ```
        Menu CSV (44 items)
              │ embed ครั้งแรกเท่านั้น
              ▼ OpenAIEmbeddings (text-embedding-3-small)
        FAISS Vector Store  ←→  save/load จาก disk (faiss_index/)
              │
        User Query (free text)
              │ embed
              ▼
        similarity_search_with_score(query, k=30)
              │
              ▼ allergen hard filter + price filter
        Top-K Candidates
              │
              ▼ score_item() + similarity_bonus (×2.0)
              ▼ dp_knapsack(budget)
              ▼ verify_result()
        Final Response
        ```

        **เมื่อไหร่ใช้ RAG vs Keyword Search:**

        | สถานการณ์ | Tool ที่ใช้ |
        |-----------|-----------|
        | "มีเมนูแซลมอนอะไรบ้าง" | `search_menu_items` (keyword) |
        | "อยากได้อะไรมันๆ ละลายในปาก" | `semantic_search_menu` (RAG) |
        | "จัดงบ 300 ชอบกุ้ง" | `build_optimal_set` (keyword + DP) |
        | "จัดงบ 400 อยากได้รสเข้มข้น" | `rag_augmented_build` (RAG + DP) |

        ---

        ## Allergen Policy

        | ประเภท | การจัดการ |
        |--------|----------|
        | **Allergen** (แพ้) | บล็อกอย่างเด็ดขาด — ไม่เข้า DP เลย |
        | **Dislike** (ไม่ชอบ) | ยังเข้า DP แต่ score ต่ำกว่า |

        ข้อมูล allergen มาจากคอลัมน์ `allergens_verified` ในฐานข้อมูล
        **ไม่ได้ตรวจจาก description** เพื่อลดความเสี่ยงพลาด

        ---
        """
    )

    st.markdown(
        '<div class="disclaimer">⚠️ <b>Disclaimer:</b> ข้อมูล allergen มาจาก dataset จำลองเท่านั้น '
        'ไม่รับประกันการปนเปื้อนจริงในร้าน '
        'กรุณาแจ้งพนักงานโดยตรงก่อนสั่งอาหารหากมีอาการแพ้รุนแรง</div>',
        unsafe_allow_html=True,
    )
