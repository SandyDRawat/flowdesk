import json,tempfile,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
from pathlib import Path
from server import Handler,Store,App
class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();cls.http=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.http.app=App(Store(Path(cls.tmp.name)/'http.sqlite3'));cls.url=f'http://127.0.0.1:{cls.http.server_port}'
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls):cls.http.shutdown();cls.http.server_close();cls.thread.join();cls.tmp.cleanup()
    def request(self,path,data=None,headers=None):
        h={'Content-Type':'application/json'};h.update(headers or {})
        return urllib.request.urlopen(urllib.request.Request(self.url+path,data=json.dumps(data).encode() if data is not None else None,headers=h))
    def test_http_crud_and_export(self):
        with self.request('/api/create',{'title':'HTTP lifecycle'}) as r:i=json.load(r)['id']
        for status in ['in_progress','todo','in_progress','done']:
            with self.request('/api/status',{'id':i,'status':status}) as r:self.assertEqual(r.status,200)
        with self.request('/api/task?id='+str(i)) as r:
            d=json.load(r);self.assertEqual(d['task']['status'],'done');self.assertEqual(len(d['sessions']),2)
        with self.request('/api/export') as r:self.assertIn('events',json.load(r))
    def test_static_and_traversal(self):
        for path in ['/','/app.js','/style.css']:
            with self.request(path) as r:self.assertEqual(r.status,200);self.assertTrue(r.read());self.assertIn('frame-ancestors',r.headers['Content-Security-Policy'])
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/../server.py')
        self.assertEqual(e.exception.code,404);e.exception.close()
    def test_host_origin_content_type_validation(self):
        for headers in [{'Host':'evil.example'},{'Origin':'https://evil.example'},{'Content-Type':'text/plain'}]:
            with self.subTest(headers=headers),self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/create',{'title':'must not save'},headers)
            self.assertEqual(e.exception.code,403);e.exception.close()
    def test_invalid_api_input(self):
        with self.assertRaises(urllib.error.HTTPError) as e:self.request('/api/create',{'title':''})
        self.assertEqual(e.exception.code,400);e.exception.close()

    def test_reports_and_place_api(self):
        with self.request('/api/state') as r:today=json.load(r)['today']
        with self.request('/api/create',{'title':'Daily report API'}) as r:task_id=json.load(r)['id']
        with self.request('/api/place',{'id':task_id,'day':today}) as r:self.assertEqual(r.status,200)
        with self.request('/api/report?kind=daily&day='+today) as r:
            report=json.load(r);self.assertFalse(report['finalized']);self.assertIn(task_id,[t['id'] for t in report['tasks']])
        with self.request('/api/report?kind=weekly&day='+today+'&format=markdown') as r:
            self.assertIn('text/markdown',r.headers['Content-Type']);self.assertIn(b'# Flowdesk weekly report',r.read())
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/report?kind=invalid')
        self.assertEqual(error.exception.code,400);error.exception.close()

    def test_health_and_guide(self):
        with self.request('/api/health') as response:
            data=json.load(response);self.assertEqual(data['app'],'Flowdesk');self.assertTrue(data['ok']);self.assertIn('managed',data)
        for path in ['/guide.html','/guide.css','/mcp-guide.md']:
            with self.request(path) as response:self.assertEqual(response.status,200);self.assertTrue(response.read())

    def test_api_key_is_write_only_and_same_origin(self):
        key='synthetic-http-test-value'
        with self.request('/api/ai-key',{'key':key}) as r:
            result=json.load(r);self.assertTrue(result['configured']);self.assertNotIn(key,json.dumps(result))
        for endpoint in ['/api/state','/api/export']:
            with self.request(endpoint) as r:self.assertNotIn(key,r.read().decode())
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/ai-key',{'key':key},{'Origin':'https://evil.example'})
        self.assertEqual(error.exception.code,403);error.exception.close()
        with self.request('/api/ai-key',{'remove':True}) as r:self.assertFalse(json.load(r)['configured'])
