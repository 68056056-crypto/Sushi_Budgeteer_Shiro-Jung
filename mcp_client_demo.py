"""Demo MCP client: launches mcp_server.py as a subprocess (stdio transport)
and calls every tool, the resource, and the prompt template in sequence, so
you can see the Model Context Protocol working end-to-end without needing
Claude Desktop or another external MCP host.

Usage:
    python mcp_client_demo.py
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    server_params = StdioServerParameters(command=sys.executable, args=["mcp_server.py"])

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            print("=== Tools available ===")
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"  - {t.name}: {t.description}")

            print("\n=== search_menu(keyword='แซลมอน') ===")
            result = await session.call_tool("search_menu", {"keyword": "แซลมอน"})
            print(result.content[0].text[:800])

            print("\n=== filter_menu(allergens=['crustacean']) ===")
            result = await session.call_tool("filter_menu", {"allergens": ["crustacean"]})
            print(result.content[0].text[:800])

            print("\n=== build_set(budget=300, allergens=['crustacean'], preferred_keywords=['แซลมอน']) ===")
            result = await session.call_tool(
                "build_set",
                {
                    "budget": 300,
                    "allergens": ["crustacean"],
                    "preferred_keywords": ["แซลมอน"],
                },
            )
            print(result.content[0].text[:1200])

            print("\n=== verify_set(budget=300, allergens=['crustacean']) ===")
            result = await session.call_tool("verify_set", {"budget": 300, "allergens": ["crustacean"]})
            print(result.content[0].text[:800])

            print("\n=== clarify(missing=['budget']) ===")
            result = await session.call_tool("clarify", {"missing": ["budget"]})
            print(result.content[0].text)

            tool_names = {t.name for t in tools.tools}
            if "semantic_search" in tool_names:
                print("\n=== semantic_search(query='ของทะเลสดๆ มันๆ') ===")
                result = await session.call_tool(
                    "semantic_search", {"query": "ของทะเลสดๆ มันๆ", "k": 5}
                )
                print(result.content[0].text[:800])
            else:
                print("\n(semantic_search / rag_build_set unavailable — faiss-cpu/langchain-openai not installed)")

            print("\n=== Resources available ===")
            resources = await session.list_resources()
            for r in resources.resources:
                print(f"  - {r.uri} ({r.name})")
            catalog = await session.read_resource("sushiro://menu/catalog")
            print(f"  catalog length: {len(catalog.contents[0].text)} chars")

            print("\n=== Prompts available ===")
            prompts = await session.list_prompts()
            for p in prompts.prompts:
                print(f"  - {p.name}")
            prompt_result = await session.get_prompt(
                "budget_optimizer",
                {"budget": "300", "allergens": "กุ้ง", "preferences": "แซลมอน"},
            )
            print(f"  rendered prompt: {prompt_result.messages[0].content.text}")


if __name__ == "__main__":
    asyncio.run(main())
