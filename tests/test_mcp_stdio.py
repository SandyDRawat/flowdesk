"""Real SDK client/server handshake and tool calls over subprocess stdio."""
import asyncio, json, os, sys, tempfile, unittest
from pathlib import Path
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    AVAILABLE=True
except ImportError:AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'Run with .venv/bin/python for MCP SDK integration tests')
class MCPProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_tools_and_duplicate_safe_scheduling(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);db=root/'mcp.sqlite3';script=Path(__file__).resolve().parents[1]/'mcp_server.py'
            params=StdioServerParameters(command=sys.executable,args=[str(script),'--db',str(db),'--workspace-root',str(root)],env=dict(os.environ,CLAUDE_PROJECT_DIR=str(root)))
            async with stdio_client(params) as (read,write):
                async with ClientSession(read,write) as session:
                    result=await session.initialize();self.assertEqual(result.serverInfo.name,'Flowdesk')
                    tools=await session.list_tools();self.assertEqual(len(tools.tools),10)
                    async def call(name,args):
                        r=await session.call_tool(name,args)
                        self.assertFalse(r.isError,str(r.content))
                        return r.structuredContent
                    workspace=await call('flowdesk_workspace',{});self.assertEqual(workspace['workspace_root'],str(root.resolve()))
                    args={'title':'Record MCP integration test','project_path':tmp,'kind':'issue','source_key':'test:integration'}
                    one=await call('flowdesk_capture_work',args);two=await call('flowdesk_capture_work',args)
                    self.assertTrue(one['created']);self.assertFalse(two['created']);self.assertEqual(one['task']['id'],two['task']['id'])
                    plan=await call('flowdesk_day_plan',{});self.assertEqual(len(plan['tasks']),1)
                    search=await call('flowdesk_find_tasks',{'query':'integration'});self.assertEqual(search['tasks'][0]['id'],one['task']['id'])
                    await call('flowdesk_set_status',{'task_id':one['task']['id'],'status':'in_progress'})
                    held=await call('flowdesk_set_status',{'task_id':one['task']['id'],'status':'waiting','waiting_on':'QA','waiting_note':'My work is done'})
                    self.assertEqual(held['task']['waiting_on'],'QA');self.assertIsNone(held['task']['finished_at'])
                    await call('flowdesk_set_status',{'task_id':one['task']['id'],'status':'done'})
                    comments=await call('flowdesk_add_comment',{'task_id':one['task']['id'],'text':'Verified and delivered'})
                    self.assertEqual(comments['comments'][0]['status'],'done')
                    report=await call('flowdesk_get_report',{});self.assertFalse(report['finalized'])
                    invalid=await session.call_tool('flowdesk_capture_work',{'title':'No','project_path':'/private'});self.assertTrue(invalid.isError)
                    invalid=await session.call_tool('flowdesk_capture_work',{'title':'No','kind':'invalid'});self.assertTrue(invalid.isError)
                    unchanged=await call('flowdesk_find_tasks',{});self.assertEqual(unchanged['total_matches'],1)
