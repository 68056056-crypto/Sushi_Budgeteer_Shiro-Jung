"""Exercise the real SQLite MCP server over stdio without an OpenAI key."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def main():
    root=Path(__file__).resolve().parent
    env={k:v for k,v in os.environ.items() if k in {'SUSHI_DB_PATH','SUSHI_DATA_MODE'}}
    params=StdioServerParameters(command=sys.executable,args=[str(root/'mcp_server.py')],cwd=str(root),env=env)
    async with stdio_client(params) as (r,w):
        async with ClientSession(r,w) as session:
            await session.initialize()
            async def call(name,args):
                result=await session.call_tool(name,args)
                if result.isError: raise RuntimeError(result.content[0].text)
                return json.loads(result.content[0].text)
            print('Tools:',', '.join(t.name for t in (await session.list_tools()).tools))
            db_status=await call('database_status',{})
            print('Database:',db_status)
            print('Search:',await call('search_menu',{'keyword':'แซลมอน'}))
            candidate=await call('build_set',{'budget':300,'drink_selection':['ชาเขียวร้อน'],'drink_quantity':2})
            if candidate['status']!='candidate': raise RuntimeError(candidate)
            verified=await call('verify_set',{'result_id':candidate['result_id']})
            assert verified['passed'],verified
            print('Verified total:',verified['recomputed_total'])
            catalog=await session.read_resource('sushiro://menu/catalog')
            assert len(json.loads(catalog.contents[0].text))==db_status['row_count']
            assert (await session.get_prompt('budget_optimizer',{'budget':'300'})).messages
            print('MCP integration passed (no LLM API used).')

if __name__=='__main__': asyncio.run(main())
