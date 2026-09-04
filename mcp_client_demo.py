"""
mcp_client_demo.py — Demo Client สำหรับทดสอบ Sushi-Budgeteer MCP Server

รัน MCP server ใน subprocess แล้วเรียก tools ผ่าน stdio transport
ใช้สำหรับ demo / ทดสอบว่า MCP server ทำงานได้จริง

วิธีรัน:
    python mcp_client_demo.py

ต้องการ:
    pip install mcp
    OPENAI_API_KEY ต้องตั้งไว้แล้ว (สำหรับ RAG tools)
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"), override=False)
except ImportError:
    pass

# ---------------------------------------------------------------------------
# MCP client imports
# ---------------------------------------------------------------------------
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _pretty(label: str, data: str | dict, indent: int = 2):
    """Print formatted output"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print('='*60)
    if isinstance(data, str):
        try:
            parsed = json.loads(data)
            print(json.dumps(parsed, ensure_ascii=False, indent=indent))
        except Exception:
            print(data)
    else:
        print(json.dumps(data, ensure_ascii=False, indent=indent, default=str))


def _call_result(result) -> str:
    """Extract text content from MCP tool result"""
    if hasattr(result, "content") and result.content:
        for block in result.content:
            if hasattr(block, "text"):
                return block.text
    return str(result)


# ---------------------------------------------------------------------------
# Demo scenarios
# ---------------------------------------------------------------------------

async def run_demo():
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(ROOT, "mcp_server.py")],
        env={**os.environ},
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # ---- 0. List available tools ----
            tools_list = await session.list_tools()
            _pretty(
                "Available MCP Tools",
                {t.name: t.description[:60] + "..." for t in tools_list.tools},
            )

            # ---- 1. search_menu ----
            result = await session.call_tool("search_menu", {"keyword": "แซลมอน"})
            data = json.loads(_call_result(result))
            _pretty(
                f"search_menu(keyword='แซลมอน') → {data['count']} items",
                [{"id": i["item_id"], "name": i["name_th"], "price": i["price_baht"]}
                 for i in data["items"][:5]],
            )

            # ---- 2. filter_menu ----
            result = await session.call_tool(
                "filter_menu",
                {"allergens": ["fish"], "dislikes": ["ปลาหมึก"]},
            )
            data = json.loads(_call_result(result))
            _pretty(
                "filter_menu(allergens=['fish'], dislikes=['ปลาหมึก'])",
                data["counts"],
            )

            # ---- 3. build_set ----
            result = await session.call_tool(
                "build_set",
                {
                    "budget": 300,
                    "preferred_keywords": ["แซลมอน", "กุ้ง"],
                    "allergens": ["fish"],
                    "min_items": 3,
                },
            )
            data = json.loads(_call_result(result))
            _pretty(
                f"build_set(budget=300, allergens=['fish']) → feasible={data['feasible']}",
                {
                    "message":    data["message"],
                    "total_price": data["total_price"],
                    "utilization": f"{data['budget_utilization_pct']}%",
                    "items": [i["name_th"] for i in data["selected_items"]],
                },
            )

            # ---- 4. verify_set ----
            if data.get("selected_items"):
                result = await session.call_tool(
                    "verify_set",
                    {
                        "selected_items": data["selected_items"],
                        "budget": 300,
                        "allergens": ["fish"],
                    },
                )
                verify_data = json.loads(_call_result(result))
                _pretty(
                    f"verify_set → passed={verify_data['passed']}",
                    {
                        "passed":     verify_data["passed"],
                        "violations": verify_data["allergen_violations"],
                        "issues":     verify_data["issues"],
                    },
                )

            # ---- 5. clarify ----
            result = await session.call_tool(
                "clarify",
                {"reason": "ไม่มีงบประมาณ", "missing_fields": ["budget"]},
            )
            data = json.loads(_call_result(result))
            _pretty("clarify(reason='ไม่มีงบประมาณ')", data)

            # ---- 6. Read resource: menu catalog ----
            resources = await session.list_resources()
            _pretty(
                "Available Resources",
                [str(r.uri) for r in resources.resources],
            )

            catalog = await session.read_resource("sushiro://menu/catalog")
            catalog_data = json.loads(catalog.contents[0].text)
            _pretty(
                "Resource: sushiro://menu/catalog (summary)",
                {
                    "total_items": catalog_data["total_items"],
                    "categories":  catalog_data["categories"],
                    "price_range": catalog_data["price_range"],
                },
            )

            # ---- 7. RAG tools (ถ้ามี API key + index) ----
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if api_key and api_key.startswith("sk-"):
                print("\n[RAG] API key พบแล้ว ทดสอบ semantic_search...")
                result = await session.call_tool(
                    "semantic_search",
                    {"query": "อยากได้อะไรมันๆ ละลายในปาก", "top_k": 3},
                )
                data = json.loads(_call_result(result))
                if "error" in data:
                    print(f"[RAG] {data['error']}")
                else:
                    _pretty(
                        f"semantic_search(query='อะไรมันๆ') → {data['count']} results",
                        [
                            {
                                "name":       r["name_th"],
                                "similarity": r["similarity_score"],
                                "price":      r["price_baht"],
                            }
                            for r in data["results"]
                        ],
                    )

                # RAG build set
                result = await session.call_tool(
                    "rag_build_set",
                    {
                        "budget": 350,
                        "preference_description": "รสเข้มข้น มีทั้งปลาดิบและของทอด",
                        "allergens": [],
                        "min_items": 4,
                    },
                )
                data = json.loads(_call_result(result))
                _pretty(
                    f"rag_build_set(budget=350) → feasible={data.get('feasible')}",
                    {
                        "message":    data.get("message", ""),
                        "source":     data.get("retrieval_source", ""),
                        "candidates": data.get("retrieved_candidates", 0),
                        "items":      [i["name_th"] for i in data.get("selected_items", [])],
                    },
                )
            else:
                print("\n[RAG] ข้าม — ไม่พบ OPENAI_API_KEY (ใส่ใน .env เพื่อทดสอบ RAG tools)")

            # ---- 8. Prompt template ----
            prompts = await session.list_prompts()
            _pretty(
                "Available Prompts",
                [p.name for p in prompts.prompts],
            )

            prompt_result = await session.get_prompt(
                "budget_optimizer",
                {"budget": "400", "allergens": "crustacean", "preferences": "แซลมอน"},
            )
            _pretty(
                "Prompt: budget_optimizer(budget=400, allergens='crustacean')",
                prompt_result.messages[0].content.text
                if prompt_result.messages else "(empty)",
            )

    print("\n" + "="*60)
    print("  Demo เสร็จสมบูรณ์!")
    print("="*60)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(run_demo())
