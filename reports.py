"""Time-zone-aware, immutable end-of-day and end-of-week snapshots."""
import datetime as dt
import json
from zoneinfo import ZoneInfo


def bounds(day, timezone):
    date=dt.date.fromisoformat(day); zone=ZoneInfo(timezone)
    return (dt.datetime.combine(date,dt.time.min,zone).astimezone(dt.timezone.utc),
            dt.datetime.combine(date+dt.timedelta(days=1),dt.time.min,zone).astimezone(dt.timezone.utc))


def as_of(task, events, cutoff):
    """Undo later edits so historical reports never borrow today's title/status."""
    result=dict(task)
    for event in reversed(events):
        if dt.datetime.fromisoformat(event['at'])<cutoff: continue
        detail=json.loads(event['detail']); kind=event['kind']
        if kind=='edited':
            for key,change in detail.items(): result[key]=change['from']
        elif kind=='status_changed': result['status']=detail['from']
        elif kind=='archived': result['archived']=0
        elif kind=='restored': result['archived']=1
    return result


def union_seconds(ranges):
    total=0; end=None
    for a,b in sorted(ranges):
        if end is None or a>end: total+=(b-a).total_seconds()
        elif b>end: total+=(b-end).total_seconds()
        end=max(end,b) if end else b
    return total


def daily(store,db,day,today):
    timezone=store.settings(db)['timezone']; start,end=bounds(day,timezone)
    cutoff=min(end,dt.datetime.now(dt.timezone.utc)); closed=day<today
    if closed: cutoff=end
    all_events=[dict(r) for r in db.execute('SELECT * FROM events ORDER BY id')]
    by_task={}
    for event in all_events: by_task.setdefault(event['task_id'],[]).append(event)
    plans={r['task_id']:dict(r) for r in db.execute('SELECT * FROM plans WHERE day=? ORDER BY position,task_id',(day,))}
    sessions=[dict(r) for r in db.execute('SELECT * FROM sessions')]
    rows=[]; intervals=[]
    for task in db.execute('SELECT * FROM tasks ORDER BY id'):
        if dt.datetime.fromisoformat(task['created_at'])>=cutoff: continue
        history=by_task.get(task['id'],[]); t=as_of(task,history,cutoff)
        events=[e for e in history if start<=dt.datetime.fromisoformat(e['at'])<cutoff]
        total=0; lifetime=0
        for s in sessions:
            if s['task_id']!=t['id']: continue
            begin=dt.datetime.fromisoformat(s['started_at']); finish=min(dt.datetime.fromisoformat(s['ended_at']) if s['ended_at'] else cutoff,cutoff)
            lifetime+=max(0,(finish-begin).total_seconds())
            a,b=max(start,begin),finish
            if b>a: total+=(b-a).total_seconds(); intervals.append((a,b))
        completed=t['status']=='done' and any(e['kind']=='status_changed' and json.loads(e['detail'])['to']=='done' for e in events)
        if t['id'] not in plans and not events and not total: continue
        p=plans.get(t['id'])
        rows.append({k:t.get(k) for k in ['id','title','category','priority','difficulty','kind','project_path','status','archived','original_estimate_minutes','estimate_minutes','duration_days','due_date','waiting_on','waiting_note','contact','related_task_id','assignee']} | {
            'planned':bool(p),'position':p['position'] if p else None,'planned_estimate_minutes':p['estimate_minutes'] if p else 0,
            'rolled_from':p['rolled_from'] if p else None,'tracked_seconds':round(total,3),'lifetime_seconds':round(lifetime,3),
            'completed_today':completed,'carried_forward':bool(p and t['status']!='done' and not t['archived'])})
    rows.sort(key=lambda t:(not t['planned'],t['position'] if t['position'] is not None else t['id']))
    completed=[t for t in rows if t['completed_today']]
    original=sum(t['original_estimate_minutes'] for t in completed)
    actual=sum(t['lifetime_seconds'] for t in completed)
    return {'kind':'daily','start':day,'end':day,'timezone':timezone,'finalized':closed,'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),
        'tasks':rows,'summary':{'planned':sum(t['planned'] for t in rows),'completed':len(completed),'carried_forward':sum(t['carried_forward'] for t in rows),
        'planned_minutes':sum(t['planned_estimate_minutes'] for t in rows),'task_seconds':round(sum(t['tracked_seconds'] for t in rows),3),
        'active_seconds':round(union_seconds(intervals),3),'original_completed_minutes':original,'completed_actual_seconds':actual,
        'estimate_ratio':round(actual/(original*60),3) if original else None},
        'events':[e for e in all_events if start<=dt.datetime.fromisoformat(e['at'])<cutoff]}


def get(store,db,kind,day,today):
    date=dt.date.fromisoformat(day)
    if kind not in ['daily','weekly']: raise ValueError('Report kind must be daily or weekly.')
    if day>today: raise ValueError('Reports are available for today and past dates.')
    if kind=='weekly': date-=dt.timedelta(days=date.weekday())
    key=date.isoformat()
    existing=db.execute('SELECT content FROM reports WHERE kind=? AND period_start=?',(kind,key)).fetchone()
    if existing: return json.loads(existing[0])
    if kind=='daily': result=daily(store,db,key,today)
    else:
        end=date+dt.timedelta(days=6)
        days=[get(store,db,'daily',(date+dt.timedelta(days=n)).isoformat(),today) for n in range(7) if (date+dt.timedelta(days=n)).isoformat()<=today]
        completed={t['id']:t for report in days for t in report['tasks'] if t['completed_today']}
        planned={t['id'] for report in days for t in report['tasks'] if t['planned']}
        original=sum(t['original_estimate_minutes'] for t in completed.values());actual=sum(t['lifetime_seconds'] for t in completed.values())
        result={'kind':'weekly','start':key,'end':end.isoformat(),'timezone':store.settings(db)['timezone'],'finalized':end.isoformat()<today,
            'generated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'days':days,'tasks':list(completed.values()),
            'summary':{'planned':len(planned),'completed':len(completed),'carried_forward':days[-1]['summary']['carried_forward'] if days else 0,
            'planned_minutes':sum(d['summary']['planned_minutes'] for d in days),'task_seconds':sum(d['summary']['task_seconds'] for d in days),
            'active_seconds':sum(d['summary']['active_seconds'] for d in days),'original_completed_minutes':original,'completed_actual_seconds':actual,
            'estimate_ratio':round(actual/(original*60),3) if original else None}}
    if result['finalized']:
        db.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?,?,?)',(kind,key,result['end'],result['generated_at'],json.dumps(result)))
    return result


def catch_up(store,db,today):
    settings=store.settings(db)
    cursor=settings.get('report_next_day')
    if not cursor:
        earliest=db.execute('SELECT MIN(created_at) FROM tasks').fetchone()[0]
        cursor=dt.datetime.fromisoformat(earliest).astimezone(ZoneInfo(settings['timezone'])).date().isoformat() if earliest else today
    day=dt.date.fromisoformat(cursor)
    while day.isoformat()<today:
        get(store,db,'daily',day.isoformat(),today)
        if day.weekday()==6: get(store,db,'weekly',day.isoformat(),today)
        day+=dt.timedelta(days=1)
    db.execute('INSERT INTO settings VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('report_next_day',json.dumps(max(cursor,today))))


def markdown(report):
    s=report['summary']; lines=[f"# Flowdesk {report['kind']} report",f"{report['start']} — {report['end']} · {report['timezone']}",
        'Final snapshot' if report['finalized'] else 'Live draft — the period is still open','',
        f"- Planned tasks: {s['planned']}",f"- Completed tasks: {s['completed']}",f"- Carrying forward: {s['carried_forward']}",
        f"- Tracked task time: {s['task_seconds']/3600:.2f} hours",f"- Active clock time (overlap counted once): {s['active_seconds']/3600:.2f} hours",'']
    if report['kind']=='weekly':
        lines+=['## Day by day','| Day | Planned | Done | Carried | Task hours |','|---|---:|---:|---:|---:|']
        for d in report['days']:
            x=d['summary'];lines.append(f"| {d['start']} | {x['planned']} | {x['completed']} | {x['carried_forward']} | {x['task_seconds']/3600:.2f} |")
    lines+=['','## Tasks','| Task | Status | Original estimate | Tracked time |','|---|---|---:|---:|']
    for t in report['tasks']:
        title=(t['title']+((' — Waiting on: '+t.get('waiting_on','')) if t.get('waiting_on') and t['status'] in ['waiting','blocked'] else '')+((' — '+t.get('waiting_note','')) if t.get('waiting_note') and t['status'] in ['waiting','blocked'] else '')).replace('|','\\|').replace('\n',' ')
        lines.append(f"| #{t['id']} {title} | {t['status']} | {t['original_estimate_minutes']}m | {t['tracked_seconds']/60:.1f}m |")
    return '\n'.join(lines)+'\n'
