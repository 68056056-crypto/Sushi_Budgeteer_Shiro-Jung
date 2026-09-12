"""RAG (Retrieval-Augmented Generation) layer: semantic menu search via FAISS.

Plain substring search in tools.search_menu_items fails on queries like
"อยากได้อะไรมันๆ รสเข้มข้น" (something rich and buttery-tasting) because none
of those words literally appear in any menu name. This module embeds every
menu row with an OpenAI embedding model and stores the vectors in a FAISS
index so we can retrieve by *meaning* instead of exact text.

Import of this module is optional: if faiss-cpu / langchain-openai are not
installed, `tools.py` catches the ImportError and simply runs without the
RAG tools. RAG here is a retrieval layer only — every candidate it returns
still goes through the same allergen hard-filter and the same DP knapsack as
the non-RAG path, so it never bypasses safety or the optimization step.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from langchain_core.documents import Document
from langchain_core.tools import tool
from langchain_community.vectorstores import FAISS
from langchain_openai import OpenAIEmbeddings

from .optimizer import (
    aggregate_by_item_id,
    dp_knapsack,
    matches_any_keyword,
    menu_records,
    parse_allergen_tags,
    score_item,
    set_last_result,
)

_INDEX_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "faiss_index"
)

_vector_store: Optional[FAISS] = None
_embeddings: Optional[OpenAIEmbeddings] = None


def _get_embeddings() -> OpenAIEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddings(model="text-embedding-3-small")
    return _embeddings


def _row_to_document(row: Dict[str, Any]) -> Document:
    content = " | ".join(
        [
            str(row.get("name_th", "")),
            str(row.get("name_en", "")),
            str(row.get("category", "")),
            str(row.get("description_th", "")),
            str(row.get("keywords", "")).replace(";", " "),
        ]
    )
    return Document(page_content=content, metadata={"item_id": row["item_id"]})


def get_vector_store(force_rebuild: bool = False) -> FAISS:
    """Build (or load a cached) FAISS index over the menu dataset.

    The index is persisted to disk under faiss_index/ so subsequent runs
    don't re-embed all rows (and re-spend API credits) unless the dataset
    changed or force_rebuild=True is requested.
    """
    global _vector_store
    if _vector_store is not None and not force_rebuild:
        return _vector_store

    embeddings = _get_embeddings()

    if not force_rebuild and os.path.isdir(_INDEX_DIR):
        _vector_store = FAISS.load_local(
            _INDEX_DIR, embeddings, allow_dangerous_deserialization=True
        )
        return _vector_store

    docs = [_row_to_document(row) for row in menu_records()]
    _vector_store = FAISS.from_documents(docs, embeddings)
    os.makedirs(_INDEX_DIR, exist_ok=True)
    _vector_store.save_local(_INDEX_DIR)
    return _vector_store


def semantic_search_menu(
    query: str,
    k: int = 5,
    allergens: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """Semantic search over the menu; allergen hard-filter still applies.

    Returns menu rows augmented with a `similarity` field in [0, 1], derived
    from the FAISS L2 distance (`1 / (1 + distance)`), highest first.
    """
    store = get_vector_store()
    allergens_norm = {str(a).strip().lower() for a in (allergens or [])}
    menu_by_id = {row["item_id"]: row for row in menu_records()}

    raw_hits = store.similarity_search_with_score(query, k=max(k * 3, k))

    results: List[Dict[str, Any]] = []
    for doc, distance in raw_hits:
        row = menu_by_id.get(doc.metadata.get("item_id"))
        if row is None:
            continue
        if allergens_norm & parse_allergen_tags(row.get("allergens_verified")):
            continue
        item = dict(row)
        item["similarity"] = round(1.0 / (1.0 + max(0.0, float(distance))), 4)
        results.append(item)
        if len(results) >= k:
            break
    return results


def rag_augmented_build(
    query: str,
    budget: float,
    allergens: Optional[List[str]] = None,
    dislikes: Optional[List[str]] = None,
    preferred_keywords: Optional[List[str]] = None,
    hard_exclude_keywords: Optional[List[str]] = None,
    must_include_keywords: Optional[List[str]] = None,
    k_candidates: int = 30,
    max_items: int = 20,
) -> Dict[str, Any]:
    """RAG retrieval -> score_item (+ similarity bonus) -> dp_knapsack.

    Candidates come from semantic search instead of the full menu, then get
    scored with the same score_item() used everywhere else, plus a
    similarity bonus (similarity * 2.0), before going through the same
    dp_knapsack() optimizer as build_optimal_set. hard_exclude_keywords and
    must_include_keywords apply the same hard filtering as build_optimal_set
    (see tools.py) so RAG can't bypass those constraints either.
    """
    candidates = semantic_search_menu(query, k=k_candidates, allergens=allergens)
    dislikes = dislikes or []
    hard_exclude_keywords = hard_exclude_keywords or []
    must_include_keywords = must_include_keywords or []

    candidates = [
        row
        for row in candidates
        if not (hard_exclude_keywords and matches_any_keyword(row, hard_exclude_keywords))
        and not (must_include_keywords and not matches_any_keyword(row, must_include_keywords))
    ]

    scored: List[Dict[str, Any]] = []
    for row in candidates:
        item = dict(row)
        is_disliked = matches_any_keyword(row, dislikes)
        base_score = score_item(
            row, preferred_keywords=preferred_keywords, budget=budget, is_disliked=is_disliked
        )
        item["score"] = round(base_score + item.get("similarity", 0.0) * 2.0, 3)
        scored.append(item)

    selected = dp_knapsack(scored, budget, max_items=max_items)
    total_price = round(sum(float(it["price_baht"]) for it in selected), 2)

    result = {
        "query": query,
        # Aggregated by dish (quantity + subtotal_baht) — same repeat-capable
        # DP as build_optimal_set, so 2 plates of one dish show as one line.
        "selected": aggregate_by_item_id(selected),
        "total_price": total_price,
        "budget": budget,
        "budget_used_pct": round(total_price / budget * 100, 1) if budget else 0.0,
        "item_count": len(selected),
        "distinct_dish_count": len({it["item_id"] for it in selected}),
        "candidates_considered": len(candidates),
        "allergens_requested": sorted({str(a).strip().lower() for a in (allergens or [])}),
        "hard_exclude_keywords": list(hard_exclude_keywords),
        "must_include_keywords": list(must_include_keywords),
    }
    set_last_result(result)
    return result


# ----------------------------------------------------------------------
# LangChain tool wrappers (added to AGENT_TOOLS by tools.py when available)
# ----------------------------------------------------------------------
@tool
def semantic_search_menu_tool(
    query: str,
    k: int = 5,
    allergens: Optional[List[str]] = None,
) -> str:
    """ค้นหาเมนูซูชิด้วยความหมาย (semantic search) ผ่าน FAISS Vector Store.

    ใช้เมื่อคำค้นของผู้ใช้เป็นคำอธิบายทั่วไปที่ไม่ตรงกับชื่อเมนูโดยตรง เช่น
    "อยากได้อะไรมันๆ เข้มข้น" หรือ "ของกินเล่นเผ็ดๆ" ซึ่ง search_menu_items
    แบบ substring จะหาไม่เจอ. ยังคงกรอง allergen อย่างเข้มงวดเช่นเดิม.
    คืนค่ารายการเมนูที่ใกล้เคียงที่สุดพร้อมคะแนนความคล้าย (similarity 0-1).
    """
    results = semantic_search_menu(query, k=k, allergens=allergens)
    payload = {
        "query": query,
        "count": len(results),
        "items": [
            {
                "item_id": r.get("item_id"),
                "name_th": r.get("name_th"),
                "name_en": r.get("name_en"),
                "category": r.get("category"),
                "price_baht": r.get("price_baht"),
                "allergens_verified": r.get("allergens_verified"),
                "similarity": r.get("similarity"),
            }
            for r in results
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


@tool
def rag_augmented_build_tool(
    query: str,
    budget: float,
    allergens: Optional[List[str]] = None,
    dislikes: Optional[List[str]] = None,
    preferred_keywords: Optional[List[str]] = None,
    hard_exclude_keywords: Optional[List[str]] = None,
    must_include_keywords: Optional[List[str]] = None,
) -> str:
    """จัดชุดเมนูที่คุ้มค่าที่สุดโดยเริ่มจากการค้นหาเชิงความหมาย (RAG) ก่อน
    แล้วจึงคำนวณด้วย DP Knapsack เช่นเดียวกับ build_optimal_set.

    ใช้แทน build_optimal_set เมื่อคำขอของผู้ใช้เป็นคำอธิบายเชิงความหมาย
    (เช่น "อยากได้ของทะเลสดๆ ไม่เอาของทอด") มากกว่าการระบุชื่อเมนูตรงๆ.
    hard_exclude_keywords (ตัดออกเด็ดขาด เช่น "ของดิบ") และ must_include_keywords
    ("เอาเฉพาะ" กุ้ง/ปลา) ทำงานเหมือน build_optimal_set ทุกประการ — RAG ไม่ได้
    ข้ามผ่านข้อจำกัดเหล่านี้. หลังเรียก tool นี้ ต้องเรียก verify_result เสมอ.
    """
    result = rag_augmented_build(
        query=query,
        budget=budget,
        allergens=allergens,
        dislikes=dislikes,
        preferred_keywords=preferred_keywords,
        hard_exclude_keywords=hard_exclude_keywords,
        must_include_keywords=must_include_keywords,
    )
    return json.dumps(result, ensure_ascii=False, indent=2)


RAG_TOOLS = [semantic_search_menu_tool, rag_augmented_build_tool]
