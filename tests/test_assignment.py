import tempfile, unittest, datetime as dt
from pathlib import Path
from unittest.mock import patch
from server import Store
class AssignmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'tasks.db')
    def tearDown(self):self.tmp.cleanup()
    def test_assignment_stops_timer_requires_owner_and_frees_slot(self):
        first=self.store.mutate('create',{'title':'Delegate','category':'admin'})['id']
        second=self.store.mutate('create',{'title':'Next','category':'admin'})['id']
        self.store.mutate('status',{'id':first,'status':'in_progress'})
        with self.assertRaises(ValueError):self.store.mutate('status',{'id':first,'status':'assigned','assignee':' '})
        self.assertEqual(self.store.detail(first)['task']['status'],'in_progress')
        self.store.mutate('status',{'id':first,'status':'assigned','assignee':'Reviewer','waiting_note':'Schedule interviews'})
        d=Store(self.store.path).detail(first)
        self.assertEqual(d['task']['assignee'],'Reviewer');self.assertIsNone(d['task']['finished_at']);self.assertTrue(d['sessions'][0]['ended_at'])
        self.store.mutate('status',{'id':second,'status':'in_progress'})
        self.store.mutate('status',{'id':first,'status':'assigned','assignee':'New owner'})
        self.assertEqual(self.store.detail(first)['task']['assignee'],'New owner')
    def test_assigned_rollover_and_report(self):
        yesterday=(dt.date.fromisoformat(self.store.state()['today'])-dt.timedelta(days=1)).isoformat()
        with patch.object(self.store,'today',return_value=yesterday),patch('server.now',return_value=yesterday+'T03:00:00+00:00'):
            with self.store.db() as db:db.execute("UPDATE settings SET value=? WHERE key='last_rollover_day'",('"'+yesterday+'"',))
            task=self.store.mutate('create',{'title':'Handoff','day':yesterday})['id']
            self.store.mutate('place',{'id':task,'day':yesterday,'status':'assigned','assignee':'Team'})
        self.assertIn(task,[p['task_id'] for p in self.store.state()['plans']])
        row=next(t for t in self.store.report('daily',yesterday)['tasks'] if t['id']==task)
        self.assertEqual(row['status'],'assigned');self.assertEqual(row['assignee'],'Team');self.assertTrue(row['carried_forward'])

    def test_assigning_inbox_task_adds_it_to_today_without_starting(self):
        task=self.store.mutate('create',{'title':'Inbox delegation'})['id']
        self.store.mutate('status',{'id':task,'status':'assigned','assignee':'Team'})
        self.assertIn(task,[p['task_id'] for p in self.store.state()['plans']])
        self.assertEqual(self.store.detail(task)['sessions'],[])
        self.store.mutate('status',{'id':task,'status':'assigned','assignee':'Another person'})
        self.assertEqual(sum(p['task_id']==task for p in self.store.state()['plans']),1)
