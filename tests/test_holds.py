import datetime as dt, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from server import Store
class HoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'holds.sqlite3')
    def tearDown(self):self.tmp.cleanup()
    def task(self,title='Work'):return self.store.mutate('create',{'title':title})['id']
    def test_waiting_stops_timer_frees_slot_and_is_not_done(self):
        self.store.mutate('settings',{'total_limit':1})
        first=self.task();second=self.task('Next')
        self.store.mutate('status',{'id':first,'status':'in_progress'})
        self.store.mutate('status',{'id':first,'status':'waiting','waiting_on':'Reviewer','waiting_note':'My part is complete; needs approval.'})
        details=self.store.detail(first)
        self.assertEqual(details['task']['status'],'waiting');self.assertIsNone(details['task']['finished_at']);self.assertTrue(details['sessions'][0]['ended_at'])
        self.store.mutate('status',{'id':second,'status':'in_progress'})
        with self.assertRaises(ValueError):self.store.mutate('status',{'id':first,'status':'in_progress'})
        self.store.mutate('status',{'id':second,'status':'todo'});self.store.mutate('status',{'id':first,'status':'in_progress'})
        self.assertEqual(len(self.store.detail(first)['sessions']),2)
    def test_blocked_note_changes_without_new_sessions(self):
        task=self.task()
        self.store.mutate('status',{'id':task,'status':'blocked','waiting_on':'API access','waiting_note':'Need credentials'})
        self.store.mutate('status',{'id':task,'status':'blocked','waiting_note':'Access requested'})
        d=self.store.detail(task);self.assertEqual(d['task']['waiting_note'],'Access requested');self.assertEqual(d['sessions'],[])
        self.assertTrue(any(e['kind']=='edited' for e in d['events']))
    def test_invalid_hold_does_not_stop_timer_or_partially_change_notes(self):
        task=self.task();self.store.mutate('status',{'id':task,'status':'in_progress'})
        with self.assertRaises(ValueError):self.store.mutate('status',{'id':task,'status':'blocked','waiting_on':'Team','waiting_note':None})
        d=self.store.detail(task);self.assertEqual(d['task']['status'],'in_progress');self.assertEqual(d['task']['waiting_on'],'');self.assertIsNone(d['sessions'][0]['ended_at'])
    def test_waiting_rolls_over_and_reports_context(self):
        today=dt.date.fromisoformat(self.store.state()['today']);yesterday=(today-dt.timedelta(days=1)).isoformat()
        with patch.object(self.store,'today',return_value=yesterday),patch('server.now',return_value=yesterday+'T03:00:00+00:00'):
            with self.store.db() as db:db.execute("UPDATE settings SET value=? WHERE key='last_rollover_day'",('"'+yesterday+'"',))
            task=self.store.mutate('create',{'title':'Review','day':yesterday})['id']
            self.store.mutate('status',{'id':task,'status':'waiting','waiting_on':'QA','waiting_note':'My changes are ready'})
        state=self.store.state();self.assertIn(task,[p['task_id'] for p in state['plans']])
        report=self.store.report('daily',yesterday);row=next(t for t in report['tasks'] if t['id']==task)
        self.assertEqual(row['status'],'waiting');self.assertEqual(row['waiting_on'],'QA');self.assertFalse(row['completed_today']);self.assertTrue(row['carried_forward'])

    def test_planning_and_held_columns_do_not_consume_admin_slots(self):
        with self.store.db() as db:today=self.store.today(db)
        ids=[self.store.mutate('create',{'title':str(i),'category':'admin'})['id'] for i in range(6)]
        self.store.mutate('status',{'id':ids[0],'status':'in_progress'})
        for task,status in zip(ids[1:],['not_started','todo','waiting','blocked',None]):
            payload={'id':task,'day':today}
            if status:payload['status']=status
            self.store.mutate('place',payload)
        self.assertEqual(len(self.store.state()['plans']),6)
        with self.assertRaisesRegex(ValueError,'admin running limit'):
            self.store.mutate('status',{'id':ids[-1],'status':'in_progress'})
        self.store.mutate('status',{'id':ids[0],'status':'blocked'})
        self.store.mutate('status',{'id':ids[-1],'status':'in_progress'})
        self.assertEqual(sum(t['status']=='in_progress' for t in self.store.state()['tasks']),1)
    def test_edit_admin_limit_and_lowering_safely(self):
        self.store.mutate('settings',{'admin_limit':2})
        ids=[self.store.mutate('create',{'title':str(i),'kind':'communication'})['id'] for i in range(2)]
        for task in ids:self.store.mutate('status',{'id':task,'status':'in_progress'})
        with self.assertRaises(ValueError):self.store.mutate('settings',{'admin_limit':1})
        self.assertEqual(self.store.state()['settings']['admin_limit'],2)
        self.store.mutate('status',{'id':ids[0],'status':'waiting'})
        self.store.mutate('settings',{'admin_limit':1})
        self.assertEqual(Store(self.store.path).state()['settings']['admin_limit'],1)
