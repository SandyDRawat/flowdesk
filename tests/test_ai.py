import io,json,os,tempfile,unittest,urllib.error
from pathlib import Path
from unittest.mock import patch
from server import Store,App
import ai

SUGGESTION={'title':'Clarified task','description':'A clearer description','steps':['First step'],'acceptance_criteria':['Observable outcome'],'risks':['No project context']}
class Response:
    def __init__(self,data):self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):return json.dumps(self.data).encode()
class AITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.db');self.app=App(self.store)
        self.tid=self.store.mutate('create',{'title':'Original','description':'Original notes','ai_enabled':True,'project_path':'/private/example','contact':'Private contact'})['id']
    def tearDown(self):self.tmp.cleanup()
    def test_preview_contains_only_task_text(self):
        payload=self.app.preview(self.tid)['payload']
        self.assertEqual(payload,{'task':{'title':'Original','description':'Original notes','kind':'task'}})
    def test_session_key_never_persisted_and_disconnect_invalidates_preview(self):
        key='synthetic-test-value'
        self.app.configure_key({'key':key});p=self.app.preview(self.tid)
        self.assertTrue(self.app.key_status()['configured'])
        self.assertNotIn(key,json.dumps(self.store.state()));self.assertNotIn(key,self.store.path and Path(self.store.path).read_bytes().decode(errors='ignore'))
        self.app.configure_key({'remove':True});self.assertFalse(self.app.key_status()['configured']);self.assertEqual(self.app.previews,{})
        with patch.dict(os.environ,{},clear=True):self.assertFalse(App(self.store).key_status()['configured'])
    def test_valid_generation_keeps_original_until_apply(self):
        self.app.configure_key({'key':'synthetic-test-value'});p=self.app.preview(self.tid)
        response=Response({'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps(SUGGESTION)}]}}]})
        with patch('ai.urllib.request.build_opener') as factory:
            factory.return_value.open.return_value=response
            result=self.app.enrich(self.tid,p['token'])
            request=factory.return_value.open.call_args.args[0];body=json.loads(request.data)
            self.assertEqual(request.get_header('X-goog-api-key'),'synthetic-test-value')
            self.assertNotIn('synthetic-test-value',request.full_url)
            self.assertNotIn('/private/example',request.data.decode())
            self.assertEqual(body['generationConfig']['responseJsonSchema'],ai.SCHEMA)
        self.assertEqual(result['suggestion'],SUGGESTION)
        self.assertEqual(self.store.detail(self.tid)['task']['title'],'Original')
        self.assertEqual(len(self.store.detail(self.tid)['suggestions']),1)
        with self.assertRaises(ValueError):self.app.enrich(self.tid,p['token'])
    def test_provider_error_never_exposes_key_or_body(self):
        error=urllib.error.HTTPError('https://example.invalid',403,'secret-body',{},io.BytesIO(b'secret-body'))
        with patch('ai.urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect=error
            with self.assertRaises(ValueError) as caught:ai.rewrite('synthetic-test-value',ai.DEFAULT_MODEL,{'task':{}})
        self.assertNotIn('secret-body',str(caught.exception));self.assertIn('403',str(caught.exception))
    def test_bad_response_or_model_rejected(self):
        for bad in [None,{},dict(SUGGESTION,title=''),dict(SUGGESTION,steps='wrong'),dict(SUGGESTION,risks=[1])]:
            with self.assertRaises(ValueError):ai.validate_suggestion(bad)
        with self.assertRaises(ValueError):ai.rewrite('unused','https://example.invalid',{})
        self.assertIsNone(ai.NoRedirect().redirect_request(None,None,302,'',{},'https://example.invalid'))
    def test_task_changed_during_response_is_not_saved(self):
        self.app.configure_key({'key':'synthetic-test-value'});p=self.app.preview(self.tid)
        def generate(*args):
            self.store.mutate('update',{'id':self.tid,'title':'Edited meanwhile'})
            return SUGGESTION
        with patch('ai.rewrite',side_effect=generate),self.assertRaisesRegex(ValueError,'Task changed'):
            self.app.enrich(self.tid,p['token'])
        self.assertEqual(self.store.detail(self.tid)['suggestions'],[])
