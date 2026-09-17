#!/usr/bin/env python3
"""Flowdesk: single-user loopback task workspace, Python standard library only."""
import argparse, contextlib, datetime as dt, hashlib, json, mimetypes, os, re, secrets, sqlite3, threading, time, urllib.request, urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from zoneinfo import ZoneInfo
import reports
import ai

ROOT = Path(__file__).resolve().parent
VERSION = '1.3.0'
def default_db():
    override=os.environ.get('FLOWDESK_DB')
    if override:return str(Path(override).expanduser().resolve())
    return str(ROOT/'data'/'flowdesk.sqlite3')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 category TEXT NOT NULL DEFAULT 'coding', priority TEXT NOT NULL DEFAULT 'medium', difficulty TEXT NOT NULL DEFAULT 'medium',
 estimate_minutes INTEGER NOT NULL DEFAULT 60, original_estimate_minutes INTEGER NOT NULL DEFAULT 60,
 duration_days INTEGER NOT NULL DEFAULT 1, due_date TEXT, status TEXT NOT NULL DEFAULT 'not_started',
 ai_enabled INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 first_started_at TEXT, finished_at TEXT, archived INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS plans (day TEXT NOT NULL, task_id INTEGER NOT NULL REFERENCES tasks(id), position INTEGER NOT NULL,
 estimate_minutes INTEGER NOT NULL, rolled_from TEXT, PRIMARY KEY(day,task_id));
CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), started_at TEXT NOT NULL, ended_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS one_open_session ON sessions(task_id) WHERE ended_at IS NULL;
CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, task_id INTEGER REFERENCES tasks(id), at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS suggestions (id INTEGER PRIMARY KEY, task_id INTEGER NOT NULL REFERENCES tasks(id), created_at TEXT NOT NULL, model TEXT NOT NULL, context_hash TEXT NOT NULL, content TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS events_task ON events(task_id,id);
CREATE TABLE IF NOT EXISTS reports (kind TEXT NOT NULL, period_start TEXT NOT NULL, period_end TEXT NOT NULL, generated_at TEXT NOT NULL, content TEXT NOT NULL, PRIMARY KEY(kind,period_start));
CREATE TABLE IF NOT EXISTS task_sources (project_path TEXT NOT NULL, source_key TEXT NOT NULL, task_id INTEGER NOT NULL REFERENCES tasks(id), PRIMARY KEY(project_path,source_key));
'''
DEFAULTS = {'timezone':'Asia/Kolkata','coding_limit':3,'admin_limit':1,'total_limit':4,'daily_minutes':480,'repo_path':'','ai_model':ai.DEFAULT_MODEL}

def now(): return dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds')
def parse_time(v): return dt.datetime.fromisoformat(v)
def date_value(v):
    if not isinstance(v,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',v): raise ValueError('Use a date in YYYY-MM-DD format.')
    return dt.date.fromisoformat(v)
def integer(v, lo, hi, label):
    if isinstance(v,bool) or not isinstance(v,int) or not lo <= v <= hi: raise ValueError(f'{label} must be an integer from {lo} to {hi}.')
    return v

class Store:
    def __init__(self,path):
        self.path = str(path)
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript(SCHEMA)
            columns={r[1] for r in db.execute('PRAGMA table_info(tasks)')}
            for name,definition in [('project_path',"TEXT NOT NULL DEFAULT ''"),('kind',"TEXT NOT NULL DEFAULT 'task'"),('waiting_on',"TEXT NOT NULL DEFAULT ''"),('waiting_note',"TEXT NOT NULL DEFAULT ''"),('contact',"TEXT NOT NULL DEFAULT ''"),('assignee',"TEXT NOT NULL DEFAULT ''"),('related_task_id','INTEGER REFERENCES tasks(id)'),('subtask_position','INTEGER NOT NULL DEFAULT 0')]:
                if name not in columns: db.execute(f'ALTER TABLE tasks ADD COLUMN {name} {definition}')
            for k,v in DEFAULTS.items(): db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',(k,json.dumps(v)))
            db.execute('INSERT OR IGNORE INTO settings VALUES (?,?)',('last_rollover_day',json.dumps(self.today(db))))
            db.execute("UPDATE settings SET value=? WHERE key='ai_model' AND value LIKE '%claude%'",(json.dumps(ai.DEFAULT_MODEL),))
            db.execute('CREATE INDEX IF NOT EXISTS task_project_title ON tasks(project_path,title)')
    @contextlib.contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=15); db.row_factory=sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA journal_mode=WAL')
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback(); raise
        finally: db.close()
    def settings(self,db): return {r['key']:json.loads(r['value']) for r in db.execute('SELECT * FROM settings')}
    def today(self,db): return dt.datetime.now(ZoneInfo(self.settings(db)['timezone'])).date().isoformat()
    def event(self,db,tid,kind,detail): db.execute('INSERT INTO events(task_id,at,kind,detail) VALUES (?,?,?,?)',(tid,now(),kind,json.dumps(detail)))
    def task(self,db,tid):
        t=db.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
        if not t: raise ValueError('Task not found.')
        return dict(t)
    def add_plan(self,db,tid,day,rolled=None):
        t=self.task(db,tid)
        position=db.execute('SELECT COALESCE(MAX(position),-1)+1 FROM plans WHERE day=?',(day,)).fetchone()[0]
        c=db.execute('INSERT OR IGNORE INTO plans VALUES (?,?,?,?,?)',(day,tid,position,t['estimate_minutes'],rolled))
        if c.rowcount: self.event(db,tid,'rolled_over' if rolled else 'planned',{'day':day,'from':rolled})
    def rollover(self,db,today=None):
        today=today or self.today(db)
        # Advance a durable cursor once per day. Re-reading must not resurrect deliberately unplanned tasks.
        last=self.settings(db).get('last_rollover_day',today)
        day=date_value(last)+dt.timedelta(days=1)
        while day.isoformat()<=today:
            prev=(day-dt.timedelta(days=1)).isoformat(); current=day.isoformat()
            rows=db.execute("SELECT p.task_id FROM plans p JOIN tasks t ON t.id=p.task_id WHERE p.day=? AND t.status!='done' AND t.archived=0 ORDER BY p.position,p.task_id",(prev,)).fetchall()
            for r in rows: self.add_plan(db,r['task_id'],current,prev)
            day+=dt.timedelta(days=1)
        if today>last:
            db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(today),'last_rollover_day'))
        reports.catch_up(self,db,today)
    def validate_task(self,data,old=None,db=None):
        t=dict(old or {})
        allowed=['title','description','category','priority','difficulty','estimate_minutes','duration_days','due_date','ai_enabled','project_path','kind','waiting_on','waiting_note','contact','related_task_id','assignee']
        t.update({k:data[k] for k in allowed if k in data})
        title=t.get('title','')
        if not isinstance(title,str) or not 1<=len(title.strip())<=300: raise ValueError('A task title is required (up to 300 characters).')
        t['title']=title.strip()
        for k,values,default in [('category',['coding','admin'],'coding'),('priority',['high','medium','low'],'medium'),('difficulty',['easy','medium','hard'],'medium')]:
            t.setdefault(k,default)
            if t[k] not in values: raise ValueError(f'Invalid {k}.')
        t.setdefault('description','')
        if not isinstance(t['description'],str) or len(t['description'])>20000: raise ValueError('Description must be text, up to 20,000 characters.')
        t['estimate_minutes']=integer(t.get('estimate_minutes',60),1,100000,'Estimate')
        t['duration_days']=integer(t.get('duration_days',1),1,365,'Duration')
        t.setdefault('due_date',None)
        if t['due_date']: date_value(t['due_date'])
        t['due_date']=t['due_date'] or None
        if t.get('ai_enabled',False) not in (True,False,0,1): raise ValueError('AI toggle must be boolean.')
        for field,limit in [('waiting_on',300),('waiting_note',5000),('contact',300),('assignee',300)]:
            t.setdefault(field,'')
            if not isinstance(t[field],str) or len(t[field])>limit: raise ValueError(f'{field} must be text, up to {limit} characters.')
        t.setdefault('project_path',''); t.setdefault('kind','task')
        if not isinstance(t['project_path'],str) or len(t['project_path'])>2000: raise ValueError('Invalid project path.')
        if t['kind'] not in ['task','issue','communication']: raise ValueError('Kind must be task, issue, or communication.')
        if t['kind']=='communication': t['category']='admin'
        related=t.get('related_task_id')
        t['related_task_id']=integer(related,1,2147483647,'Related task') if related not in (None,'') else None
        if t['related_task_id']:
            if old and t['related_task_id']==old['id']: raise ValueError('A task cannot link to itself.')
            if db is not None:
                parent=self.task(db,t['related_task_id']);seen=set()
                while parent:
                    if parent['id'] in seen or (old and parent['id']==old['id']): raise ValueError('Subissues cannot form a circular parent link.')
                    seen.add(parent['id'])
                    parent=self.task(db,parent['related_task_id']) if parent['related_task_id'] else None
        t['ai_enabled']=int(bool(t.get('ai_enabled',False)))
        return {k:t[k] for k in allowed}
    def capacity(self,db,category,exclude=None,settings=None):
        s=settings or self.settings(db)
        rows=db.execute("SELECT category,title FROM tasks WHERE status='in_progress' AND (? IS NULL OR id!=?)",(exclude,exclude)).fetchall()
        if len(rows)>=s['total_limit']: raise ValueError('All running slots are occupied. Pause, hold, or finish a running task, or change limits in Settings. Planning without starting is still available.')
        if sum(r['category']==category for r in rows)>=s['coding_limit' if category=='coding' else 'admin_limit']:
            raise ValueError(f"The {category} running limit ({s['coding_limit' if category=='coding' else 'admin_limit']}) is full: {', '.join(r['title'] for r in rows if r['category']==category)}. Pause, hold, or finish a running item, or change limits in Settings. Waiting and blocked items do not count.")
    def change_status(self,db,tid,status,today,details=None):
        t=self.task(db,tid)
        if status not in ['not_started','todo','in_progress','waiting','blocked','assigned','done']: raise ValueError('Unknown status.')
        if t['archived']: raise ValueError('Restore the task before starting it.')
        if status=='assigned':
            assignee=(details or {}).get('assignee',t['assignee'])
            if not isinstance(assignee,str) or not assignee.strip() or len(assignee)>300: raise ValueError('Enter the person or team this task is assigned to.')
        if details and status in ['waiting','blocked','assigned']:
            changes={}
            for field,limit in [('waiting_on',300),('waiting_note',5000),('assignee',300)]:
                if field not in details: continue
                value=details[field]
                if not isinstance(value,str) or len(value)>limit: raise ValueError(f'{field} must be text, up to {limit} characters.')
                if value!=t[field]:
                    changes[field]={'from':t[field],'to':value}
                    db.execute(f'UPDATE tasks SET {field}=?,updated_at=? WHERE id=?',(value,now(),tid))
            if changes:self.event(db,tid,'edited',changes)
        if status=='assigned': self.add_plan(db,tid,today)
        if status==t['status']: return
        stamp=now()
        if status=='in_progress':
            self.capacity(db,t['category'],tid)
            db.execute('INSERT INTO sessions(task_id,started_at) VALUES (?,?)',(tid,stamp))
            db.execute('UPDATE tasks SET first_started_at=COALESCE(first_started_at,?) WHERE id=?',(stamp,tid))
            self.add_plan(db,tid,today)
        else: db.execute('UPDATE sessions SET ended_at=? WHERE task_id=? AND ended_at IS NULL',(stamp,tid))
        db.execute('UPDATE tasks SET status=?,finished_at=?,updated_at=? WHERE id=?',(status,stamp if status=='done' else None,stamp,tid))
        self.event(db,tid,'status_changed',{'from':t['status'],'to':status})
    def mutate(self,action,data):
        with self.db() as db:
            self.rollover(db)
            today=self.today(db)
            tid=data.get('id')
            if action=='create':
                t=self.validate_task(data,db=db); stamp=now()
                keys=list(t); vals=list(t.values())
                c=db.execute(f"INSERT INTO tasks ({','.join(keys)},original_estimate_minutes,created_at,updated_at) VALUES ({','.join('?' for _ in range(len(keys)+3))})",vals+[t['estimate_minutes'],stamp,stamp]); tid=c.lastrowid
                self.event(db,tid,'created',t)
                if t['related_task_id']:
                    db.execute('UPDATE tasks SET subtask_position=(SELECT COALESCE(MAX(subtask_position),0)+1 FROM tasks WHERE related_task_id=? AND id!=?) WHERE id=?',(t['related_task_id'],tid,tid))
                if data.get('day'):
                    date_value(data['day'])
                    if data['day']<today: raise ValueError('Plan new tasks for today or a future day.')
                    self.add_plan(db,tid,data['day'])
            elif action=='reorder-subissues':
                self.task(db,tid)
                ids=data.get('ids')
                existing=[r[0] for r in db.execute('SELECT id FROM tasks WHERE related_task_id=? AND archived=0',(tid,))]
                if not isinstance(ids,list) or any(type(i) is not int for i in ids) or len(ids)!=len(set(ids)) or set(ids)!=set(existing): raise ValueError('The subissue list changed. Refresh and try again.')
                for position,child in enumerate(ids):db.execute('UPDATE tasks SET subtask_position=? WHERE id=?',(position,child))
                self.event(db,tid,'subissues_reordered',{'ids':ids})
            elif action=='comment':
                task=self.task(db,tid)
                text=data.get('text')
                if not isinstance(text,str) or not text.strip() or len(text)>5000: raise ValueError('Enter a status comment (up to 5,000 characters).')
                self.event(db,tid,'comment_added',{'text':text.strip(),'status':task['status']})
            elif action=='update':
                old=self.task(db,tid); t=self.validate_task(data,old,db=db)
                if old['status']=='in_progress': self.capacity(db,t['category'],tid)
                changes={k:{'from':old[k],'to':v} for k,v in t.items() if v!=old[k]}
                db.execute(f"UPDATE tasks SET {','.join(k+'=?' for k in t)},updated_at=? WHERE id=?",list(t.values())+[now(),tid])
                if changes: self.event(db,tid,'edited',changes)
            elif action=='status':
                self.change_status(db,tid,data.get('status'),today,data)
            elif action=='plan':
                day=data.get('day',today); date_value(day)
                if day<today: raise ValueError('Past plans are read-only.')
                t=self.task(db,tid)
                if t['archived'] or t['status']=='done': raise ValueError('Only open tasks can be planned.')
                self.add_plan(db,tid,day)
            elif action=='place':
                day=data.get('day',today); date_value(day)
                if day<today: raise ValueError('Past plans are read-only.')
                t=self.task(db,tid)
                if t['archived']: raise ValueError('Restore this task first.')
                if t['status']=='done' and not db.execute('SELECT 1 FROM plans WHERE day=? AND task_id=?',(day,tid)).fetchone(): raise ValueError('Reopen a completed task before planning it.')
                status=data.get('status')
                if status and day!=today: raise ValueError('Change status from today; future days are for planning only.')
                self.add_plan(db,tid,day)
                if status: self.change_status(db,tid,status,today,data)
                before=data.get('before_id')
                if before is not None and before!=tid:
                    ids=[r[0] for r in db.execute('SELECT task_id FROM plans WHERE day=? ORDER BY position,task_id',(day,))]
                    if before not in ids: raise ValueError('The target task is no longer in this plan. Refresh and try again.')
                    ids.remove(tid); ids.insert(ids.index(before),tid)
                    for position,i in enumerate(ids): db.execute('UPDATE plans SET position=? WHERE day=? AND task_id=?',(position,day,i))
                    self.event(db,None,'plan_reordered',{'day':day,'ids':ids})
            elif action=='unplan':
                day=data.get('day',today); date_value(day)
                if day<today: raise ValueError('Past plans are read-only.')
                if self.task(db,tid)['status']=='in_progress': raise ValueError('Pause the task before removing it from the plan.')
                db.execute('DELETE FROM plans WHERE day=? AND task_id=?',(day,tid)); self.event(db,tid,'unplanned',{'day':day})
            elif action=='reorder':
                day=data.get('day',today); date_value(day)
                if day<today: raise ValueError('Past plans are read-only.')
                ids=data.get('ids',[]); existing=[r[0] for r in db.execute('SELECT task_id FROM plans WHERE day=?',(day,))]
                if not isinstance(ids,list) or len(ids)!=len(set(ids)) or set(ids)!=set(existing): raise ValueError('The plan changed. Refresh and try again.')
                for pos,i in enumerate(ids): db.execute('UPDATE plans SET position=? WHERE day=? AND task_id=?',(pos,day,i))
                self.event(db,None,'plan_reordered',{'day':day,'ids':ids})
            elif action=='archive':
                t=self.task(db,tid)
                if t['status']=='in_progress': raise ValueError('Pause or finish the task before archiving.')
                archived=int(bool(data.get('archived',True)))
                db.execute('UPDATE tasks SET archived=?,updated_at=? WHERE id=?',(archived,now(),tid)); self.event(db,tid,'archived' if archived else 'restored',{})
            elif action=='settings':
                s=self.settings(db)
                for k in DEFAULTS:
                    if k in data: s[k]=data[k]
                for k,lo,hi in [('coding_limit',1,5),('admin_limit',1,5),('total_limit',1,5),('daily_minutes',30,1440)]: s[k]=integer(s[k],lo,hi,k)
                try: ZoneInfo(s['timezone'])
                except Exception: raise ValueError('Enter a valid IANA timezone, such as Asia/Kolkata.')
                if not isinstance(s['ai_model'],str) or not re.fullmatch('gemini-[a-zA-Z0-9._-]{1,90}',s['ai_model']): raise ValueError('Invalid model ID.')
                if s['repo_path']:
                    p=Path(s['repo_path']).expanduser().resolve()
                    if not p.is_dir(): raise ValueError('Repository folder does not exist.')
                    s['repo_path']=str(p)
                rows=db.execute("SELECT category FROM tasks WHERE status='in_progress'").fetchall()
                if len(rows)>s['total_limit'] or sum(r[0]=='coding' for r in rows)>s['coding_limit'] or sum(r[0]=='admin' for r in rows)>s['admin_limit']: raise ValueError('Pause tasks before lowering these limits.')
                for k,v in s.items(): db.execute('UPDATE settings SET value=? WHERE key=?',(json.dumps(v),k))
                self.event(db,None,'settings_updated',{k:v for k,v in s.items() if k!='repo_path'})
            else: raise ValueError('Unknown action.')
            return {'id':tid,'ok':True}
    def state(self,day=None):
        with self.db() as db:
            self.rollover(db); today=self.today(db); day=day or today; date_value(day)
            tasks=[dict(r) for r in db.execute('SELECT * FROM tasks ORDER BY created_at DESC')]
            sessions=[dict(r) for r in db.execute('SELECT * FROM sessions ORDER BY started_at')]
            stamp=dt.datetime.now(dt.timezone.utc)
            for t in tasks:
                ts=[s for s in sessions if s['task_id']==t['id']]
                t['actual_seconds']=sum(max(0,((parse_time(s['ended_at']) if s['ended_at'] else stamp)-parse_time(s['started_at'])).total_seconds()) for s in ts)
                t['running_since']=next((s['started_at'] for s in ts if not s['ended_at']),None)
            settings=self.settings(db)
            return {'today':today,'day':day,'settings':settings,'tasks':tasks,'sessions':sessions,'plans':[dict(r) for r in db.execute('SELECT * FROM plans WHERE day=? ORDER BY position,task_id',(day,))],
                'events':[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 300')],
                'history_days':[dict(r) for r in db.execute('SELECT day,COUNT(*) AS count FROM plans GROUP BY day ORDER BY day DESC LIMIT 365')],
                'service':{'managed':os.environ.get('FLOWDESK_MANAGED')=='1','version':VERSION},
                'report_archive':[dict(r) for r in db.execute('SELECT kind,period_start,period_end,generated_at FROM reports ORDER BY period_start DESC LIMIT 120')],
                'historical_tasks':self.report_in_db(db,'daily',day,today)['tasks'] if day<today else None,
                'ai_ready':False,'server_time':stamp.isoformat()}
    def detail(self,tid):
        with self.db() as db:
            return {'task':self.task(db,tid),'subissues':[dict(r) for r in db.execute('SELECT * FROM tasks WHERE related_task_id=? AND archived=0 ORDER BY subtask_position,id',(tid,))],'sessions':[dict(r) for r in db.execute('SELECT * FROM sessions WHERE task_id=? ORDER BY id DESC',(tid,))],
            'events':[dict(r) for r in db.execute('SELECT * FROM events WHERE task_id=? ORDER BY id DESC',(tid,))],
            'comments':[{'id':r['id'],'at':r['at'],**json.loads(r['detail'])} for r in db.execute("SELECT * FROM events WHERE task_id=? AND kind='comment_added' ORDER BY id DESC",(tid,))],
            'suggestions':[dict(r) for r in db.execute('SELECT * FROM suggestions WHERE task_id=? ORDER BY id DESC',(tid,))]}

    def report_in_db(self,db,kind,day,today):
        return reports.get(self,db,kind,day,today)
    def report(self,kind='daily',day=None):
        with self.db() as db:
            self.rollover(db); today=self.today(db)
            return self.report_in_db(db,kind,day or today,today)
    def ensure_task(self,data):
        """Atomic MCP capture and scheduling; exact title/source matching never overwrites user data."""
        with self.db() as db:
            self.rollover(db);today=self.today(db)
            t=self.validate_task(data,db=db);day=data.get('day',today)
            if day:
                date_value(day)
                if day<today: raise ValueError('Choose today or a future day.')
            source=data.get('source_key','')
            if not isinstance(source,str) or len(source)>1000: raise ValueError('Source key must be text, up to 1,000 characters.')
            found=None
            if source:
                found=db.execute('SELECT t.* FROM tasks t JOIN task_sources s ON s.task_id=t.id WHERE s.project_path=? AND s.source_key=?',(t['project_path'],source)).fetchone()
            normalize=lambda value:' '.join(re.findall(r'\w+',value.casefold()))
            if not found:
                found=next((r for r in db.execute("SELECT * FROM tasks WHERE project_path IN (?, '') ORDER BY project_path='',archived,status='done',id",(t['project_path'],)) if normalize(r['title'])==normalize(t['title'])),None)
            created=found is None
            if created:
                stamp=now(); keys=list(t)
                cursor=db.execute(f"INSERT INTO tasks ({','.join(keys)},original_estimate_minutes,created_at,updated_at) VALUES ({','.join('?' for _ in range(len(keys)+3))})",list(t.values())+[t['estimate_minutes'],stamp,stamp])
                tid=cursor.lastrowid; self.event(db,tid,'created',t)
                if t['related_task_id']:db.execute('UPDATE tasks SET subtask_position=(SELECT COALESCE(MAX(subtask_position),0)+1 FROM tasks WHERE related_task_id=? AND id!=?) WHERE id=?',(t['related_task_id'],tid,tid))
            else:
                tid=found['id']
                if not found['project_path'] and t['project_path']:
                    db.execute('UPDATE tasks SET project_path=?,updated_at=? WHERE id=?',(t['project_path'],now(),tid))
                    self.event(db,tid,'edited',{'project_path':{'from':'','to':t['project_path']}})
            if source: db.execute('INSERT OR IGNORE INTO task_sources VALUES (?,?,?)',(t['project_path'],source,tid))
            task=self.task(db,tid); scheduled=False; reason=None
            if day and not task['archived'] and task['status']!='done':
                self.add_plan(db,tid,day); scheduled=True
            elif day: reason='Existing task is completed or archived; it was not reopened or scheduled.'
            return {'task':task,'created':created,'scheduled':scheduled,'day':day,'reason':reason}

class App:
    def __init__(self,store):
        self.store=store;self.previews={};self.lock=threading.Lock();self.request_lock=threading.Lock()
        self.session_key=None;self.disabled=False
    def key(self):
        with self.lock:return '' if self.disabled else (self.session_key or os.environ.get('GEMINI_API_KEY',''))
    def key_status(self):
        with self.lock:
            return {'configured':bool(not self.disabled and (self.session_key or os.environ.get('GEMINI_API_KEY'))),
                    'source':'disabled' if self.disabled else 'session' if self.session_key else 'environment' if os.environ.get('GEMINI_API_KEY') else 'none'}
    def configure_key(self,data):
        with self.lock:
            if data.get('remove') is True:
                self.session_key=None;self.disabled=True;self.previews.clear()
            else:
                key=data.get('key')
                if not isinstance(key,str) or not 10<=len(key.strip())<=256 or not re.fullmatch(r'[A-Za-z0-9_-]+',key.strip()):
                    raise ValueError('Enter a valid Gemini API key.')
                self.session_key=key.strip();self.disabled=False;self.previews.clear()
        return {'ok':True,**self.key_status()}
    def preview(self,tid):
        with self.store.db() as db:
            task=self.store.task(db,tid);settings=self.store.settings(db)
        if not task['ai_enabled']:raise ValueError('Enable AI on this task first.')
        payload={'task':{k:task[k] for k in ['title','description','kind']}}
        token=secrets.token_urlsafe(24)
        with self.lock:
            self.previews={k:v for k,v in self.previews.items() if time.time()-v['time']<600}
            if len(self.previews)>=100:raise ValueError('Too many previews. Close old previews and try again later.')
            self.previews[token]={'time':time.time(),'tid':tid,'payload':payload,'model':settings['ai_model'],'updated':task['updated_at']}
        return {'payload':payload,'token':token,'model':settings['ai_model'],'files':[],'truncated':False}
    def enrich(self,tid,token):
        key=self.key()
        if not key:raise ValueError('Gemini is not connected. Add your key in Settings.')
        if not self.request_lock.acquire(blocking=False):raise ValueError('An AI request is already running. Please wait.')
        try:
            with self.lock:preview=self.previews.pop(token,None)
            if not preview or preview['tid']!=tid or time.time()-preview['time']>600:raise ValueError('Preview expired. Review the task again.')
            with self.store.db() as db:
                task=self.store.task(db,tid)
                if not task['ai_enabled'] or task['updated_at']!=preview['updated']:raise ValueError('Task changed. Review a fresh preview before sending.')
            content=ai.rewrite(key,preview['model'],preview['payload'])
            with self.store.db() as db:
                task=self.store.task(db,tid)
                if not task['ai_enabled'] or task['updated_at']!=preview['updated']:raise ValueError('Task changed while Gemini was responding. Review a fresh preview.')
                db.execute('INSERT INTO suggestions(task_id,created_at,model,context_hash,content) VALUES (?,?,?,?,?)',
                    (tid,now(),preview['model'],hashlib.sha256(json.dumps(preview['payload']).encode()).hexdigest(),json.dumps(content)))
                self.store.event(db,tid,'ai_suggested',{'model':preview['model']})
            return {'suggestion':content}
        finally:self.request_lock.release()

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,code,body,kind='application/json'):
        if isinstance(body,(dict,list)): body=json.dumps(body).encode()
        if isinstance(body,str): body=body.encode()
        self.send_response(code); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(body))); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers(); self.wfile.write(body)
    def trusted(self):
        host=self.headers.get('Host','')
        valid={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'}
        return host in valid and self.headers.get('Origin',f'http://{host}')==f'http://{host}'
    def do_GET(self):
        if not self.trusted(): return self.send(403,{'error':'Local access only.'})
        from urllib.parse import urlparse,parse_qs
        url=urlparse(self.path); q=parse_qs(url.query)
        try:
            if url.path=='/api/health':
                return self.send(200,{'app':'Flowdesk','version':VERSION,'ok':True,'managed':os.environ.get('FLOWDESK_MANAGED')=='1','pid':os.getpid(),'database':str(Path(self.server.app.store.path).resolve())})
            if url.path=='/api/state':
                state=self.server.app.store.state(q.get('day',[None])[0]);status=self.server.app.key_status()
                return self.send(200,{**state,'ai_ready':status['configured'],'ai_key_source':status['source']})
            if url.path=='/api/task': return self.send(200,self.server.app.store.detail(int(q.get('id',['0'])[0])))
            if url.path=='/api/report':
                report=self.server.app.store.report(q.get('kind',['daily'])[0],q.get('day',[None])[0])
                return self.send(200,reports.markdown(report),'text/markdown; charset=utf-8') if q.get('format')==['markdown'] else self.send(200,report)
            if url.path=='/api/export':
                with self.server.app.store.db() as db:
                    data={table:[dict(r) for r in db.execute('SELECT * FROM '+table)] for table in ['tasks','plans','sessions','events','suggestions','settings','reports','task_sources']}
                return self.send(200,{'version':1,'exported_at':now(),**data})
            path=ROOT/'static'/('index.html' if url.path=='/' else url.path.lstrip('/'))
            if path.resolve().parent!=(ROOT/'static').resolve() or not path.is_file(): return self.send(404,{'error':'Not found.'})
            self.send(200,path.read_bytes(),mimetypes.guess_type(str(path))[0] or 'application/octet-stream')
        except (ValueError,TypeError) as e: self.send(400,{'error':str(e)})
        except Exception as e:
            print(type(e).__name__); self.send(500,{'error':'Server error. No changes were applied.'})
    def do_POST(self):
        if not self.trusted() or self.headers.get('Content-Type')!='application/json': return self.send(403,{'error':'Same-origin JSON requests required.'})
        try:
            length=int(self.headers.get('Content-Length','0'))
            if length<0 or length>100000: return self.send(413,{'error':'Request too large.'})
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict): raise ValueError('Expected an object.')
            action=self.path.removeprefix('/api/')
            if action=='ai-key': result=self.server.app.configure_key(data)
            elif action=='ai-preview': result=self.server.app.preview(data.get('id'))
            elif action=='ai-enrich': result=self.server.app.enrich(data.get('id'),data.get('token'))
            else: result=self.server.app.store.mutate(action,data)
            self.send(200,result)
        except (ValueError,TypeError,KeyError) as e: self.send(400,{'error':str(e)})
        except Exception as e:
            print(type(e).__name__); self.send(500,{'error':'Server error. Check the server log.'})

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--open',action='store_true'); parser.add_argument('--port',type=int,default=8765); parser.add_argument('--db',default=default_db()); args=parser.parse_args()
    store=Store(args.db); server=ThreadingHTTPServer(('127.0.0.1',args.port),Handler); server.app=App(store)
    def rollover_loop():
        while True:
            try:
                with store.db() as db: store.rollover(db)
            except Exception as e: print('Rollover:',e)
            time.sleep(30)
    threading.Thread(target=rollover_loop,daemon=True).start()
    print(f'Flowdesk ready at http://127.0.0.1:{args.port}',flush=True)
    if args.open:
        import webbrowser
        threading.Timer(0.5,lambda:webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
if __name__=='__main__': main()
