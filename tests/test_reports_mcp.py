import concurrent.futures, contextlib, datetime as dt, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from server import Store
from reports import bounds, markdown

class ReportingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'test.sqlite3')
        with self.store.db() as db:
            for key in ['last_rollover_day','report_next_day']:db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps('2026-01-05')))
    def tearDown(self):self.tmp.cleanup()
    @contextlib.contextmanager
    def at(self,local):
        stamp=dt.datetime.fromisoformat(local+'+05:30').astimezone(dt.timezone.utc).isoformat()
        with patch('server.now',return_value=stamp),patch.object(self.store,'today',return_value=local[:10]):yield
    def create(self,title='Work',**kw):return self.store.mutate('create',{'title':title,**kw})['id']
    def test_midnight_split_and_snapshot_immutable(self):
        with self.at('2026-01-05T23:00:00'):
            i=self.create(day='2026-01-05');self.store.mutate('status',{'id':i,'status':'in_progress'})
        with self.at('2026-01-06T01:00:00'):
            self.store.mutate('status',{'id':i,'status':'done'});report=self.store.report('daily','2026-01-05')
            self.assertEqual(report['summary']['task_seconds'],3600);self.assertEqual(report['summary']['carried_forward'],1)
            self.assertEqual(report['tasks'][0]['status'],'in_progress')
            self.store.mutate('update',{'id':i,'title':'Changed next day','estimate_minutes':200})
            self.assertEqual(self.store.report('daily','2026-01-05'),report)
        with self.at('2026-01-07T01:00:00'):
            next_report=self.store.report('daily','2026-01-06')
            self.assertEqual(next_report['summary']['task_seconds'],3600);self.assertEqual(next_report['summary']['completed'],1)
            self.assertEqual(next_report['summary']['completed_actual_seconds'],7200)
    def test_overlap_and_reopened_history(self):
        with self.at('2026-01-05T10:00:00'):
            a=self.create('A',day='2026-01-05');b=self.create('B',day='2026-01-05');self.store.mutate('status',{'id':a,'status':'in_progress'})
        with self.at('2026-01-05T10:30:00'):self.store.mutate('status',{'id':b,'status':'in_progress'})
        with self.at('2026-01-05T11:00:00'):self.store.mutate('status',{'id':a,'status':'done'})
        with self.at('2026-01-05T11:30:00'):self.store.mutate('status',{'id':b,'status':'done'})
        with self.at('2026-01-06T09:00:00'):
            self.store.mutate('status',{'id':a,'status':'todo'});self.store.mutate('update',{'id':a,'title':'Tomorrow'})
            r=self.store.report('daily','2026-01-05')
            self.assertEqual(r['summary']['task_seconds'],7200);self.assertEqual(r['summary']['active_seconds'],5400)
            self.assertEqual(r['summary']['completed'],2)
            historical=self.store.state('2026-01-05')['historical_tasks'];self.assertEqual(historical[0]['title'],'A');self.assertEqual(historical[0]['status'],'done')
    def test_weekly_automatic_catchup_unique_tasks(self):
        with self.at('2026-01-05T10:00:00'):
            a=self.create('Carry',day='2026-01-05');b=self.create('Finish',day='2026-01-05');self.store.mutate('status',{'id':b,'status':'done'})
        with self.at('2026-01-12T09:00:00'):
            state=self.store.state();self.assertEqual([p['task_id'] for p in state['plans']],[a])
            report=self.store.report('weekly','2026-01-07')
            self.assertTrue(report['finalized']);self.assertEqual(len(report['days']),7)
            self.assertEqual(report['summary']['planned'],2);self.assertEqual(report['summary']['completed'],1);self.assertEqual(report['summary']['carried_forward'],1)
            self.assertEqual(len([r for r in state['report_archive'] if r['kind']=='weekly']),1)
            self.assertEqual(report,self.store.report('weekly','2026-01-05'));self.assertIn('# Flowdesk weekly report',markdown(report))
    def test_current_report_draft_not_saved(self):
        with self.at('2026-01-05T10:00:00'):
            self.create(day='2026-01-05');report=self.store.report('daily','2026-01-05')
            self.assertFalse(report['finalized'])
            with self.store.db() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM reports').fetchone()[0],0)
    def test_dst_day_boundaries(self):
        a,b=bounds('2026-03-08','America/New_York');self.assertEqual((b-a).total_seconds(),23*3600)
        a,b=bounds('2026-11-01','America/New_York');self.assertEqual((b-a).total_seconds(),25*3600)
    def test_place_atomically_rejects_full_capacity(self):
        with self.at('2026-01-05T10:00:00'):
            for n in range(3):self.store.mutate('status',{'id':self.create(str(n)),'status':'in_progress'})
            extra=self.create('Extra')
            with self.assertRaises(ValueError):self.store.mutate('place',{'id':extra,'day':'2026-01-05','status':'in_progress'})
            self.assertNotIn(extra,[p['task_id'] for p in self.store.state()['plans']])
    def test_place_from_inbox_order_and_duplicate(self):
        with self.at('2026-01-05T10:00:00'):
            a=self.create('A',day='2026-01-05');b=self.create('B')
            for _ in range(2):self.store.mutate('place',{'id':b,'day':'2026-01-05','before_id':a})
            self.assertEqual([p['task_id'] for p in self.store.state()['plans']],[b,a])
            self.assertEqual(self.store.detail(b)['task']['status'],'not_started')
    def test_future_drag_cannot_start_now(self):
        with self.at('2026-01-05T10:00:00'):
            i=self.create()
            with self.assertRaises(ValueError):self.store.mutate('place',{'id':i,'day':'2026-01-06','status':'in_progress'})
            self.assertEqual(self.store.state('2026-01-06')['plans'],[])
    def test_mcp_dedup_project_source_and_manual_tasks(self):
        with self.at('2026-01-05T10:00:00'):
            i=self.create(' Fix:   Login! ')
            data={'title':'fix login','project_path':self.tmp.name,'source_key':'github:repo#12','kind':'issue'}
            a=self.store.ensure_task(data);self.assertEqual(a['task']['id'],i);self.assertFalse(a['created']);self.assertTrue(a['scheduled'])
            b=self.store.ensure_task(data|{'title':'Different issue title'});self.assertEqual(b['task']['id'],i)
            self.assertEqual(len(self.store.state()['plans']),1)
            other=self.store.ensure_task(data|{'project_path':self.tmp.name+'/another','source_key':''});self.assertTrue(other['created'])
            self.store.mutate('status',{'id':i,'status':'done'});again=self.store.ensure_task(data);self.assertFalse(again['scheduled']);self.assertFalse(again['created'])
    def test_parallel_capture_deduplicates(self):
        data={'title':'Same work','project_path':self.tmp.name,'source_key':'work:stable'}
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:results=list(pool.map(lambda _:self.store.ensure_task(data),range(6)))
        self.assertEqual(sum(r['created'] for r in results),1);self.assertEqual(len({r['task']['id'] for r in results}),1)
    def test_old_schema_migrates_without_losing_data(self):
        import sqlite3
        path=Path(self.tmp.name)/'old.sqlite3';db=sqlite3.connect(path)
        schema=__import__('server').SCHEMA
        db.executescript(schema);db.execute("INSERT INTO tasks(title,created_at,updated_at) VALUES ('Existing','2026-01-05T10:00:00+00:00','2026-01-05T10:00:00+00:00')");db.commit();db.close()
        store=Store(path)
        with store.db() as conn:
            task=store.task(conn,1);self.assertEqual(task['title'],'Existing');self.assertEqual(task['kind'],'task');self.assertEqual(task['project_path'],'')
