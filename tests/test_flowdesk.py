import concurrent.futures, datetime as dt, json, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from server import Store, App

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'test.sqlite3';self.store=Store(self.path)
    def tearDown(self):self.tmp.cleanup()
    def create(self,**kw):return self.store.mutate('create',{'title':'Implement a feature',**kw})['id']
    def status(self,i,s):return self.store.mutate('status',{'id':i,'status':s})
    def get(self,i):return next(t for t in self.store.state()['tasks'] if t['id']==i)
    def test_persistence_and_original_estimate(self):
        i=self.create(estimate_minutes=90);self.store.mutate('update',{'id':i,'estimate_minutes':120})
        fresh=Store(self.path);t=fresh.state()['tasks'][0]
        self.assertEqual(t['original_estimate_minutes'],90);self.assertEqual(t['estimate_minutes'],120)
        self.assertEqual(len(fresh.detail(i)['events']),2)
    def test_sessions_pause_resume_finish_reopen(self):
        i=self.create();self.status(i,'in_progress');self.status(i,'in_progress');self.status(i,'todo')
        self.status(i,'in_progress');self.status(i,'done')
        d=self.store.detail(i);self.assertEqual(len(d['sessions']),2)
        self.assertTrue(all(s['ended_at'] for s in d['sessions']));self.assertIsNotNone(d['task']['finished_at'])
        first=d['task']['first_started_at'];self.status(i,'todo');self.status(i,'in_progress')
        self.assertEqual(self.get(i)['first_started_at'],first);self.assertIsNone(self.get(i)['finished_at'])
    def test_restart_keeps_timer(self):
        i=self.create();self.status(i,'in_progress');self.assertIsNotNone(Store(self.path).state()['tasks'][0]['running_since'])
    def test_coding_limit(self):
        ids=[self.create() for _ in range(4)]
        for i in ids[:3]:self.status(i,'in_progress')
        with self.assertRaisesRegex(ValueError,'coding running limit'):self.status(ids[3],'in_progress')
        self.assertEqual(len(self.store.detail(ids[3])['sessions']),0)
        self.status(ids[0],'todo');self.status(ids[3],'in_progress')
    def test_admin_limit(self):
        a=self.create(category='admin');b=self.create(category='admin');self.status(a,'in_progress')
        with self.assertRaisesRegex(ValueError,'admin running limit'):self.status(b,'in_progress')
    def test_total_limit(self):
        self.store.mutate('settings',{'total_limit':2})
        for _ in range(2):self.status(self.create(),'in_progress')
        with self.assertRaisesRegex(ValueError,'running slots'):self.status(self.create(category='admin'),'in_progress')
    def test_concurrent_starts_atomic(self):
        ids=[self.create() for _ in range(8)]
        def start(i):
            try:self.status(i,'in_progress');return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:result=list(pool.map(start,ids))
        self.assertEqual(sum(result),3);self.assertEqual(sum(t['status']=='in_progress' for t in self.store.state()['tasks']),3)
    def test_changing_category_enforces_capacity(self):
        a=self.create(category='admin');c=self.create();self.status(a,'in_progress');self.status(c,'in_progress')
        with self.assertRaises(ValueError):self.store.mutate('update',{'id':c,'category':'admin'})
        self.assertEqual(self.get(c)['category'],'coding')
    def test_rollover_missed_days_idempotent_and_unplan(self):
        today=self.store.state()['today'];old=(dt.date.fromisoformat(today)-dt.timedelta(days=3)).isoformat()
        a=self.create();b=self.create();done=self.create();archived=self.create();self.status(done,'done');self.store.mutate('archive',{'id':archived})
        with self.store.db() as db:
            for i in [b,a,done,archived]:self.store.add_plan(db,i,old)
            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(old),'last_rollover_day'))
        state=self.store.state();self.assertEqual([p['task_id'] for p in state['plans']],[b,a])
        self.assertEqual(state['plans'],self.store.state()['plans'])
        with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM plans WHERE task_id=?',(a,)).fetchone()[0],4)
        self.store.mutate('unplan',{'id':a,'day':today});self.assertNotIn(a,[p['task_id'] for p in self.store.state()['plans']])
    def test_reorder_is_persistent_and_validated(self):
        today=self.store.state()['today'];a=self.create(day=today);b=self.create(day=today)
        self.store.mutate('reorder',{'day':today,'ids':[b,a]})
        self.assertEqual([p['task_id'] for p in self.store.state()['plans']],[b,a])
        with self.assertRaises(ValueError):self.store.mutate('reorder',{'day':today,'ids':[a,a]})
    def test_past_plan_readonly(self):
        i=self.create()
        with self.assertRaises(ValueError):self.store.mutate('plan',{'id':i,'day':'2000-01-01'})
    def test_daily_estimate_snapshot(self):
        today=self.store.state()['today'];i=self.create(day=today,estimate_minutes=45)
        self.store.mutate('update',{'id':i,'estimate_minutes':120});self.assertEqual(self.store.state()['plans'][0]['estimate_minutes'],45)
    def test_archiving_active_rejected(self):
        i=self.create();self.status(i,'in_progress')
        with self.assertRaises(ValueError):self.store.mutate('archive',{'id':i})
        self.status(i,'todo');self.store.mutate('archive',{'id':i})
        with self.assertRaises(ValueError):self.status(i,'in_progress')
        self.store.mutate('archive',{'id':i,'archived':False});self.status(i,'in_progress')
    def test_input_validation(self):
        for bad in [{'title':''},{'estimate_minutes':0},{'estimate_minutes':1.5},{'category':'other'},{'duration_days':0},{'due_date':'wrong'},{'description':3}]:
            with self.subTest(bad=bad),self.assertRaises(ValueError):self.create(**bad)
        self.assertEqual(len(self.store.state()['tasks']),0)
    def test_invalid_creation_rolls_back(self):
        with self.assertRaises(ValueError):self.create(day='2000-01-01')
        self.assertEqual(len(self.store.state()['tasks']),0)
    def test_settings_validation_and_capacity(self):
        for bad in [{'total_limit':6},{'admin_limit':6},{'timezone':'Not/Real'},{'repo_path':'/this/path/does/not/exist'}]:
            with self.assertRaises(ValueError):self.store.mutate('settings',bad)
        for _ in range(3):self.status(self.create(),'in_progress')
        with self.assertRaises(ValueError):self.store.mutate('settings',{'coding_limit':2})
    def test_ai_is_opt_in_and_missing_key_explicit(self):
        app=App(self.store);i=self.create()
        with self.assertRaises(ValueError):app.preview(i)
        self.store.mutate('update',{'id':i,'ai_enabled':True});preview=app.preview(i)
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaisesRegex(ValueError,'not connected'):app.enrich(i,preview['token'])
        self.assertEqual(self.get(i)['description'],'')
    def test_ai_stale_preview_rejected(self):
        app=App(self.store);i=self.create(ai_enabled=True);p=app.preview(i);self.store.mutate('update',{'id':i,'ai_enabled':False})
        with patch.dict(os.environ,{'GEMINI_API_KEY':'test'}):
            with self.assertRaisesRegex(ValueError,'Task changed'):app.enrich(i,p['token'])

if __name__=='__main__':unittest.main()
