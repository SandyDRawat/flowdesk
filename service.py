#!/usr/bin/env python3
"""Install/manage the user's local Flowdesk login service; never needs sudo."""
import argparse, datetime as dt, json, os, plistlib, shutil, socket, sqlite3, subprocess, sys, time, urllib.request
from pathlib import Path
SOURCE=Path(__file__).resolve().parent
HOME=Path.home()
APP=HOME/'Library'/'Application Support'/'Flowdesk'
LOGS=HOME/'Library'/'Logs'/'Flowdesk'
PLIST=HOME/'Library'/'LaunchAgents'/'local.flowdesk.plist'
LABEL='local.flowdesk'
DOMAIN=f'gui/{os.getuid()}'
TARGET=f'{DOMAIN}/{LABEL}'

def run(*args,check=True):
    return subprocess.run(args,check=check,text=True,capture_output=True)
def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:8765/api/health',timeout=2) as r:return json.load(r)
    except (OSError,ValueError):return None

def wait_ready():
    for _ in range(30):
        result=health()
        if result and result.get('managed') and result.get('database')==str(APP/'data'/'flowdesk.sqlite3'):return result
        time.sleep(.5)
    raise RuntimeError(f'Flowdesk did not become healthy. Check {LOGS}/stderr.log')

def install():
    if sys.platform!='darwin':raise RuntimeError('Login service installation is for macOS.')
    if run('launchctl','print',TARGET,check=False).returncode==0:
        run('launchctl','bootout',TARGET)
        for _ in range(20):
            if not health():break
            time.sleep(.25)
    # Never migrate while an unmanaged web server is still accepting writes.
    with socket.socket() as sock:
        if sock.connect_ex(('127.0.0.1',8765))==0:raise RuntimeError('Port 8765 is still in use. Stop the existing Flowdesk server before installing.')
    APP.mkdir(parents=True,exist_ok=True);LOGS.mkdir(parents=True,exist_ok=True);PLIST.parent.mkdir(parents=True,exist_ok=True)
    data=APP/'data';data.mkdir(exist_ok=True);os.chmod(data,0o700)
    source_db=SOURCE/'data'/'flowdesk.sqlite3';target_db=data/'flowdesk.sqlite3'
    if not target_db.exists() and source_db.exists():
        staged=data/'migration.sqlite3'
        with sqlite3.connect(source_db.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(staged) as dst:
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Database integrity check failed; original data is unchanged.')
        staged.replace(target_db)
    if target_db.exists():
        backups=APP/'backups';backups.mkdir(exist_ok=True)
        stamp=dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        with sqlite3.connect(target_db) as src,sqlite3.connect(backups/f'before-install-{stamp}.sqlite3') as dst:src.backup(dst)
    for name in ['server.py','ai.py','reports.py','mcp_server.py','backup.py','requirements-mcp.txt','MCP.md','LOCAL_DEPLOYMENT.md','CLAUDE_WORKFLOW.md']:
        if (SOURCE/name).is_file():shutil.copy2(SOURCE/name,APP/name)
    shutil.copytree(SOURCE/'static',APP/'static',dirs_exist_ok=True)
    # Use the stable Homebrew entrypoint rather than a versioned Cellar path.
    python=shutil.which('python3') or sys.executable
    plist={'Label':LABEL,'ProgramArguments':[python,'-u',str(APP/'server.py'),'--db',str(target_db),'--port','8765'],
        'WorkingDirectory':str(APP),'RunAtLoad':True,'KeepAlive':True,'ThrottleInterval':10,'ProcessType':'Background',
        'EnvironmentVariables':{'FLOWDESK_MANAGED':'1','PYTHONUNBUFFERED':'1','PATH':'/opt/homebrew/bin:/usr/bin:/bin'},
        'StandardOutPath':str(LOGS/'stdout.log'),'StandardErrorPath':str(LOGS/'stderr.log')}
    PLIST.write_bytes(plistlib.dumps(plist));PLIST.chmod(0o644)
    application=HOME/'Applications'/'Flowdesk.app'/'Contents';(application/'MacOS').mkdir(parents=True,exist_ok=True)
    (application/'Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'Flowdesk','CFBundleDisplayName':'Flowdesk','CFBundleIdentifier':'local.flowdesk.app','CFBundleVersion':'1.0','CFBundlePackageType':'APPL','CFBundleExecutable':'Flowdesk','LSUIElement':True}))
    launcher=application/'MacOS'/'Flowdesk'
    launcher.write_text('#!/bin/zsh\n/usr/bin/python3 -c "" 2>/dev/null\nlaunchctl kickstart "gui/$(id -u)/local.flowdesk" >/dev/null 2>&1\n/usr/bin/open "http://127.0.0.1:8765/"\n')
    launcher.write_text(launcher.read_text().replace('/usr/bin/python3 -c "" 2>/dev/null\n',''));launcher.chmod(0o755)
    run('launchctl','enable',TARGET)
    run('launchctl','bootstrap',DOMAIN,str(PLIST))
    result=wait_ready()
    print(json.dumps({'installed':True,'health':result,'launcher':str(application.parent),'launch_agent':str(PLIST)},indent=2))

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['install','status','start','restart','stop','disable-startup']);a=p.parse_args()
    if a.action=='install':install()
    elif a.action=='status':
        result=run('launchctl','print',TARGET,check=False)
        print(json.dumps({'registered':result.returncode==0,'health':health(),'logs':str(LOGS)},indent=2))
    elif a.action=='stop':
        run('launchctl','bootout',TARGET,check=False);print('Stopped for this login session. Starts again at next login.')
    elif a.action=='disable-startup':
        run('launchctl','bootout',TARGET,check=False);run('launchctl','disable',TARGET);print('Automatic startup disabled. Your database and backups remain intact.')
    else:
        run('launchctl','enable',TARGET)
        if run('launchctl','print',TARGET,check=False).returncode!=0:run('launchctl','bootstrap',DOMAIN,str(PLIST))
        run('launchctl','kickstart',*(['-k'] if a.action=='restart' else []),TARGET)
        print(json.dumps(wait_ready(),indent=2))
if __name__=='__main__':main()
