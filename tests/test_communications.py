import tempfile, unittest
from pathlib import Path
from server import Store
class CommunicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.path=Path(self.tmp.name)/'tasks.db';self.store=Store(self.path)
    def tearDown(self): self.tmp.cleanup()
    def test_link_persistence_status_and_reporting(self):
        parent=self.store.mutate('create',{'title':'Implement feature'})['id']
        self.store.mutate('status',{'id':parent,'status':'blocked'})
        communication=self.store.mutate('create',{'title':'Ask reviewer','kind':'communication','contact':'QA','related_task_id':parent})['id']
        task=Store(self.path).detail(communication)['task']
        self.assertEqual(task['contact'],'QA');self.assertEqual(task['related_task_id'],parent);self.assertEqual(task['category'],'admin')
        self.store.mutate('status',{'id':communication,'status':'in_progress'})
        second=self.store.mutate('create',{'title':'Another call','kind':'communication'})['id']
        with self.assertRaises(ValueError):self.store.mutate('status',{'id':second,'status':'in_progress'})
        self.store.mutate('status',{'id':communication,'status':'done'})
        self.assertEqual(self.store.detail(parent)['task']['status'],'blocked')
        row=next(t for t in self.store.report()['tasks'] if t['id']==communication)
        self.assertEqual(row['contact'],'QA');self.assertEqual(row['related_task_id'],parent)
    def test_conversion_preserves_notes_and_rejects_bad_links(self):
        item=self.store.mutate('create',{'title':'Message colleague','description':'Discuss issue'})['id']
        self.store.mutate('update',{'id':item,'kind':'communication'})
        self.assertEqual(self.store.detail(item)['task']['description'],'Discuss issue')
        with self.assertRaises(ValueError):self.store.mutate('update',{'id':item,'related_task_id':item})
        with self.assertRaises(ValueError):self.store.mutate('create',{'title':'Bad link','kind':'communication','related_task_id':9999})
