import tempfile, unittest
from pathlib import Path
from server import Store
class CommentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'tasks.db')
        self.task=self.store.mutate('create',{'title':'Work','description':'Keep these notes'})['id']
    def tearDown(self):self.tmp.cleanup()
    def test_append_persists_with_status_and_does_not_change_task_or_timer(self):
        self.store.mutate('status',{'id':self.task,'status':'in_progress'})
        before=self.store.detail(self.task)
        self.store.mutate('comment',{'id':self.task,'text':' First update\nNext step '})
        self.store.mutate('status',{'id':self.task,'status':'waiting'})
        self.store.mutate('comment',{'id':self.task,'text':'Waiting for review'})
        details=Store(self.store.path).detail(self.task)
        self.assertEqual([c['status'] for c in details['comments']],['waiting','in_progress'])
        self.assertEqual(details['comments'][1]['text'],'First update\nNext step')
        self.assertTrue(details['comments'][0]['at'])
        self.assertEqual(details['task']['description'],before['task']['description'])
        self.assertEqual(len(details['sessions']),1)
        self.assertEqual(sum(e['kind']=='comment_added' for e in self.store.report()['events']),2)
    def test_invalid_comment_writes_nothing(self):
        for text in ['', '  ',None,1,'x'*5001]:
            with self.assertRaises(ValueError):self.store.mutate('comment',{'id':self.task,'text':text})
        with self.assertRaises(ValueError):self.store.mutate('comment',{'id':99999,'text':'Missing'})
        self.assertEqual(self.store.detail(self.task)['comments'],[])
