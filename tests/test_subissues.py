import tempfile,unittest
from pathlib import Path
from server import Store
class SubissueTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'db';self.store=Store(self.path)
        self.parent=self.store.mutate('create',{'title':'Resolve issue','kind':'issue'})['id']
    def tearDown(self):self.tmp.cleanup()
    def test_mixed_steps_order_persistence_and_independent_completion(self):
        ids=[self.store.mutate('create',{'title':title,'kind':kind,'related_task_id':self.parent})['id'] for title,kind in [('Do work','task'),('Ask reviewer','communication'),('Continue','task')]]
        self.assertEqual([t['id'] for t in self.store.detail(self.parent)['subissues']],ids)
        self.store.mutate('reorder-subissues',{'id':self.parent,'ids':ids[::-1]})
        self.assertEqual([t['id'] for t in Store(self.path).detail(self.parent)['subissues']],ids[::-1])
        for child in ids:self.store.mutate('status',{'id':child,'status':'done'})
        self.assertEqual(self.store.detail(self.parent)['task']['status'],'not_started')
        self.assertTrue(all(t['status']=='done' for t in self.store.detail(self.parent)['subissues']))
        self.store.mutate('status',{'id':ids[0],'status':'todo'})
        self.assertEqual(self.store.detail(ids[0])['task']['related_task_id'],self.parent)
    def test_cycles_and_incomplete_reorder_rejected(self):
        child=self.store.mutate('create',{'title':'Child','related_task_id':self.parent})['id']
        with self.assertRaises(ValueError):self.store.mutate('update',{'id':self.parent,'related_task_id':child})
        with self.assertRaises(ValueError):self.store.mutate('reorder-subissues',{'id':self.parent,'ids':[]})
        self.assertIsNone(self.store.detail(self.parent)['task']['related_task_id'])
        self.assertEqual(len(self.store.detail(self.parent)['subissues']),1)
