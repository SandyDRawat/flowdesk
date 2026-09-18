import tempfile, unittest
from pathlib import Path
from server import Store

class DeletionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.store=Store(Path(self.tmp.name)/'test.sqlite3')
    def tearDown(self): self.tmp.cleanup()
    def create(self,**values): return self.store.mutate('create',{'title':'Example',**values})['id']
    def delete(self,tid): return self.store.mutate('delete',{'id':tid,'confirmed':True})
    def test_confirmation_timer_restore_and_capacity(self):
        tid=self.create();self.store.mutate('settings',{'total_limit':1})
        self.store.mutate('status',{'id':tid,'status':'in_progress'})
        with self.assertRaises(ValueError):self.store.mutate('delete',{'id':tid})
        self.assertIsNone(self.store.detail(tid)['sessions'][0]['ended_at'])
        self.delete(tid)
        state=self.store.state()
        self.assertFalse(state['tasks']);self.assertEqual(state['deleted_tasks'][0]['id'],tid)
        self.assertTrue(self.store.detail(tid)['sessions'][0]['ended_at'])
        other=self.create(title='Other');self.store.mutate('status',{'id':other,'status':'in_progress'})
        with self.assertRaises(ValueError):self.store.mutate('archive',{'id':tid,'archived':False})
        with self.assertRaises(ValueError):self.store.mutate('update',{'id':tid,'title':'Changed'})
        self.store.mutate('restore-deleted',{'id':tid})
        self.assertEqual(self.store.detail(tid)['task']['status'],'todo')
        self.assertFalse(self.store.state()['deleted_tasks'])
        self.assertTrue(any(p['task_id']==tid for p in self.store.state()['plans']))
    def test_parent_protection_and_restore_order(self):
        parent=self.create();child=self.create(title='Follow up',kind='communication',related_task_id=parent)
        self.store.mutate('archive',{'id':child})
        with self.assertRaises(ValueError):self.delete(parent)
        self.delete(child);self.delete(parent)
        with self.assertRaises(ValueError):self.store.mutate('restore-deleted',{'id':child})
        with self.assertRaises(ValueError):self.create(related_task_id=parent)
        self.store.mutate('restore-deleted',{'id':parent});self.store.mutate('restore-deleted',{'id':child})
        self.assertEqual(self.store.detail(parent)['subissues'][0]['id'],child)
    def test_capture_does_not_resurrect_deleted_and_reports_keep_time(self):
        tid=self.create();self.store.mutate('status',{'id':tid,'status':'in_progress'});self.delete(tid)
        with self.assertRaises(ValueError):self.store.ensure_task({'title':'Example'})
        self.assertTrue(self.store.report())
        self.assertEqual(len(self.store.detail(tid)['sessions']),1)
