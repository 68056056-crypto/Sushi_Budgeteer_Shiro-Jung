"""
rag.py — RAG (Retrieval-Augmented Generation) สำหรับ Sushi-Budgeteer

ทำหน้าที่:
  1. สร้าง FAISS vector store จาก menu CSV (embed description + keywords ของทุกเมนู)
  2. เปิด semantic_search_menu tool ให้ agent เรียกค้นหาเมนูด้วยความหมาย
     เช่น "อะไรมันๆ รสเข้มข้น" → ได้ otoro, uni, salmon belly แม้ไม่มีคำตรง

ทำไม RAG ถึงต้องการในระบบนี้:
  - search_menu_items เดิมใช้ substring match เท่านั้น
    → ถ้าผู้ใช้พูดว่า "อยากได้รสครีมมี่" ไม่เจออะไรเลย
  - semantic search ช่วย retrieve เมนูที่ "ใกล้เคียงความหมาย"
    แม้คำไม่ตรงกันเลย
  - retrieved items ยังผ่าน allergen filter + DP เหมือนเดิม
    RAG เป็นแค่ขั้น retrieval ไม่ได้ข้าม safety layer
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pandas as pd
from langchain_core.tools import tool
from langchain_core.documents import Document

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

# ---------------------------------------------------------------------------
# Vector Store (singleton) — สร้างครั้งเดียว ใช้ตลอด session
# ---------------------------------------------------------------------------

_VECTOR_STORE = None
_EMBEDDINGS = None


def _get_embeddings():
    """Lazy init OpenAIEmbeddings"""
    global _EMBEDDINGS
    if _EMBEDDINGS is None:
        from langchain_openai import OpenAIEmbeddings
        _EMBEDDINGS = OpenAIEmbeddings(model="text-embedding-3-small")
    return _EMBEDDINGS


def _build_documents(df: pd.DataFrame) -> list[Document]:
    """
    แปลงแต่ละแถวใน CSV เป็น LangChain Document

    content ที่ embed ประกอบด้วย:
      - ชื่อไทย + ชื่ออังกฤษ
      - description_th
      - keywords
      - category
      - ราคา

    metadata เก็บทุก field ไว้เพื่อ return กลับหลัง retrieve
    """
    docs = []
    for _, row in df.iterrows():
        allergens_raw = row.get("allergens_verified", "")
        allergens_str = str(allergens_raw) if pd.notna(allergens_raw) else ""

        # text ที่จะถูก embed — รวมทุก field ที่มีความหมาย
        content = (
            f"ชื่อ: {row['name_th']} ({row['name_en']})\n"
            f"หมวด: {row['category']}\n"
            f"ราคา: {row['price_baht']} บาท\n"
            f"รายละเอียด: {row['description_th']}\n"
            f"keywords: {row.get('keywords', '')}"
        )

        metadata = {
            "item_id":   str(row["item_id"]),
            "name_th":   str(row["name_th"]),
            "name_en":   str(row["name_en"]),
            "category":  str(row["category"]),
            "price_baht": int(row["price_baht"]),
            "allergens_verified": allergens_str,
            "description_th": str(row["description_th"]),
        }
        docs.append(Document(page_content=content, metadata=metadata))
    return docs


def get_vector_store(force_rebuild: bool = False):
    """
    สร้างหรือโหลด FAISS vector store

    - ถ้ายังไม่มี หรือ force_rebuild=True → embed ใหม่ทั้งหมดแล้ว save ลง disk
    - ถ้ามีอยู่แล้ว → load จาก disk (เร็ว ไม่เสีย token)

    index จะถูกเก็บที่: sushi_budgeteer/faiss_index/
    """
    global _VECTOR_STORE
    if _VECTOR_STORE is not None and not force_rebuild:
        return _VECTOR_STORE

    from langchain_community.vectorstores import FAISS

    index_path = os.path.join(_THIS_DIR, "faiss_index")
    embeddings = _get_embeddings()

    if os.path.exists(index_path) and not force_rebuild:
        # โหลดจาก disk — ไม่ต้อง embed ใหม่
        _VECTOR_STORE = FAISS.load_local(
            index_path,
            embeddings,
            allow_dangerous_deserialization=True,
        )
    else:
        # สร้างใหม่จาก CSV
        csv_path = os.path.join(_THIS_DIR, "..", "sushiro_menu_dataset.csv")
        csv_path = os.path.abspath(csv_path)
        df = pd.read_csv(csv_path)
        docs = _build_documents(df)

        _VECTOR_STORE = FAISS.from_documents(docs, embeddings)
        _VECTOR_STORE.save_local(index_path)

    return _VECTOR_STORE


def rebuild_index():
    """สร้าง FAISS index ใหม่ (เรียกเมื่อ CSV เปลี่ยน)"""
    global _VECTOR_STORE
    _VECTOR_STORE = None
    return get_vector_store(force_rebuild=True)


# ---------------------------------------------------------------------------
# semantic_search_menu — RAG Tool สำหรับ Agent
# ---------------------------------------------------------------------------

@tool
def semantic_search_menu(
    query: str,
    top_k: int = 5,
    allergens_exclude: list[str] | None = None,
    max_price: int = 0,
) -> dict[str, Any]:
    """
    ค้นหาเมนูด้วยความหมาย (semantic search) ผ่าน FAISS vector store

    ต่างจาก search_menu_items (substring) ตรงที่:
      - ค้นหาด้วย "ความหมาย" ไม่ใช่คำตรงๆ
      - เช่น "อยากได้อะไรมันๆ เข้มข้น" → ได้ otoro, uni, salmon belly
      - เช่น "ของหวานเบาๆ ไม่หวานมาก" → ได้ sorbet, warabi mochi
      - เช่น "อาหารทานเล่นกรอบๆ" → ได้ gyoza, karaage, tempura

    ใช้เมื่อ:
      - ผู้ใช้อธิบายรสชาติ/ความรู้สึก ไม่ใช่ชื่อเมนูตรงๆ
      - search_menu_items ไม่เจอผลลัพธ์
      - ต้องการ "เมนูที่เหมาะกับ" บรรยากาศ/โอกาสบางอย่าง

    Args:
        query:             คำค้นเชิงความหมาย เช่น "รสมันเข้มข้น ละลายในปาก"
        top_k:             จำนวนผลลัพธ์ที่ต้องการ (default 5)
        allergens_exclude: allergen ที่ต้องกรองออก (hard constraint)
        max_price:         ราคาสูงสุด (0 = ไม่จำกัด)

    Returns:
        {
          "results": [
            {
              "item_id", "name_th", "name_en", "category",
              "price_baht", "allergens_verified", "description_th",
              "similarity_score": float,   ← คะแนนความใกล้เคียง
              "retrieval_reason": str       ← อธิบายว่าทำไมถึง retrieve มา
            }, ...
          ],
          "query": str,
          "count": int,
          "method": "semantic_rag"
        }
    """
    try:
        vs = get_vector_store()
    except Exception as e:
        return {
            "results": [],
            "query": query,
            "count": 0,
            "method": "semantic_rag",
            "error": f"Vector store unavailable: {e}",
        }

    allergens_exclude = [a.lower().strip() for a in (allergens_exclude or [])]

    # Retrieve top_k * 3 แล้วค่อย filter เพื่อให้ได้ top_k หลัง filter
    fetch_k = max(top_k * 3, 15)
    results_with_score = vs.similarity_search_with_score(query, k=fetch_k)

    filtered = []
    for doc, score in results_with_score:
        meta = doc.metadata

        # Hard filter: allergen
        item_allergens = set(
            str(meta.get("allergens_verified", "")).lower().split(";")
        ) - {""} - {"nan"}
        if allergens_exclude and item_allergens & set(allergens_exclude):
            continue

        # Price filter
        if max_price > 0 and int(meta.get("price_baht", 0)) > max_price:
            continue

        # FAISS score = L2 distance (ต่ำ = ใกล้เคียงกว่า)
        # แปลงเป็น similarity score 0–1 (สูง = ใกล้เคียงกว่า)
        similarity = float(1 / (1 + score))

        filtered.append({
            "item_id":    meta["item_id"],
            "name_th":    meta["name_th"],
            "name_en":    meta["name_en"],
            "category":   meta["category"],
            "price_baht": meta["price_baht"],
            "allergens_verified": meta["allergens_verified"],
            "description_th":     meta["description_th"],
            "similarity_score":   round(similarity, 4),
            "retrieval_reason":   f"semantic match กับ '{query}'",
        })

        if len(filtered) >= top_k:
            break

    return {
        "results": filtered,
        "query": query,
        "count": len(filtered),
        "method": "semantic_rag",
    }


# ---------------------------------------------------------------------------
# rag_augmented_build — ใช้ RAG หา candidate pool ก่อน optimize
# ---------------------------------------------------------------------------

@tool
def rag_augmented_build(
    budget: int,
    preference_description: str,
    allergens: list[str] | None = None,
    dislikes: list[str] | None = None,
    min_items: int = 1,
    max_items: int = 20,
) -> dict[str, Any]:
    """
    จัดชุดเมนูโดยใช้ RAG หา candidate pool ก่อน แล้วส่งเข้า DP Knapsack

    Flow:
      1. Embed preference_description → FAISS retrieve top candidates
      2. กรอง allergen (hard) ออก
      3. score_item() ให้แต่ละ candidate
      4. dp_knapsack() บน candidate pool นั้น
      5. verify_result() ก่อน return

    ใช้เมื่อ:
      - ผู้ใช้อธิบายความต้องการเป็นประโยคยาว เช่น
        "อยากได้เมนูที่เข้มข้น มีทั้งปลาดิบและของทอด งบ 400 บาท"
      - ต้องการ semantic matching ไม่ใช่แค่ keyword

    Args:
        budget:                 งบประมาณ (บาท)
        preference_description: คำอธิบายความต้องการ (free text)
        allergens:              allergen ที่ต้องกรองออก
        dislikes:               keyword ที่ไม่ชอบ
        min_items:              จำนวนจานขั้นต่ำ
        max_items:              จำนวนจานสูงสุด

    Returns:
        เหมือน build_optimal_set แต่มี "retrieval_source": "rag"
        และ "retrieved_candidates": จำนวน candidate ที่ RAG หามาได้
    """
    from optimizer import dp_knapsack, score_item

    allergens = [a.lower().strip() for a in (allergens or [])]
    dislikes_lower = [d.lower().strip() for d in (dislikes or [])]

    # Step 1: RAG retrieve — ดึง candidate มากพอ (top 30) เพื่อให้ DP มีตัวเลือก
    retrieve_result = semantic_search_menu.invoke({
        "query": preference_description,
        "top_k": 30,
        "allergens_exclude": allergens,
        "max_price": 0,
    })

    candidates = retrieve_result.get("results", [])

    if not candidates:
        # Fallback: ถ้า RAG ไม่เจอ ใช้ full menu
        from tools import _load_menu, _run_filter
        filter_result = _run_filter(allergens=allergens, dislikes=dislikes_lower, categories_wanted=None)
        candidates = filter_result["safe_items"] + filter_result["dislike_items"]
        retrieval_source = "fallback_full_menu"
    else:
        retrieval_source = "rag"

    if not candidates:
        return {
            "selected_items": [],
            "total_price": 0,
            "budget": budget,
            "budget_utilization_pct": 0.0,
            "total_score": 0.0,
            "item_count": 0,
            "categories_covered": [],
            "feasible": False,
            "retrieval_source": retrieval_source,
            "retrieved_candidates": 0,
            "message": "ไม่มีเมนูที่ตรงกับความต้องการหลัง filter allergen",
        }

    # Step 2: score + flag dislike
    pref_keywords = [w.lower() for w in preference_description.split() if len(w) > 1]
    items_with_score = []
    for item in candidates:
        item_allergens = set(
            str(item.get("allergens_verified", "")).lower().split(";")
        ) - {""} - {"nan"}
        if allergens and item_allergens & set(allergens):
            continue  # double-check allergen safety

        text = f"{item.get('name_th','')} {item.get('name_en','')} {item.get('category','')}".lower()
        is_disliked = any(d in text for d in dislikes_lower)

        s = score_item(
            row=item,
            preferred_keywords=pref_keywords,
            budget=budget,
            is_disliked=is_disliked,
        )
        # RAG similarity bonus: เพิ่ม score ตาม similarity (0–2 คะแนน)
        similarity_bonus = item.get("similarity_score", 0) * 2.0
        items_with_score.append({**item, "score": s + similarity_bonus})

    if not items_with_score:
        return {
            "selected_items": [], "total_price": 0, "budget": budget,
            "budget_utilization_pct": 0.0, "total_score": 0.0,
            "item_count": 0, "categories_covered": [],
            "feasible": False,
            "retrieval_source": retrieval_source,
            "retrieved_candidates": len(candidates),
            "message": "หลัง filter allergen ไม่มีเมนูเหลือ",
        }

    min_price = min(i["price_baht"] for i in items_with_score)
    if budget < min_price:
        return {
            "selected_items": [], "total_price": 0, "budget": budget,
            "budget_utilization_pct": 0.0, "total_score": 0.0,
            "item_count": 0, "categories_covered": [],
            "feasible": False,
            "retrieval_source": retrieval_source,
            "retrieved_candidates": len(candidates),
            "message": f"งบ {budget} บาท น้อยกว่าเมนูที่ถูกสุด ({min_price} บาท)",
        }

    # Step 3: DP
    selected = dp_knapsack(items=items_with_score, budget=budget, max_items=max_items)

    total_price = sum(i["price_baht"] for i in selected)
    utilization = round(total_price / budget * 100, 1) if budget > 0 else 0.0
    categories = list({i["category"] for i in selected})

    clean = [
        {k: v for k, v in i.items() if k not in ("score", "allergen_set", "similarity_score", "retrieval_reason")}
        for i in selected
    ]

    feasible = len(selected) >= min_items
    return {
        "selected_items": clean,
        "total_price": total_price,
        "budget": budget,
        "budget_utilization_pct": utilization,
        "total_score": round(sum(i["score"] for i in selected), 3),
        "item_count": len(selected),
        "categories_covered": categories,
        "feasible": feasible,
        "retrieval_source": retrieval_source,
        "retrieved_candidates": len(candidates),
        "message": (
            f"RAG จัดได้ {len(selected)} จาน รวม {total_price} บาท "
            f"(ใช้งบ {utilization}%) จาก {len(candidates)} candidates"
        ),
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

RAG_TOOLS = [semantic_search_menu, rag_augmented_build]
