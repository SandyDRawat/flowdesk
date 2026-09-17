#!/usr/bin/env python3
"""Fail closed on common accidental data/credential files in a release tree/history.
Run alongside GitLeaks; this is a privacy guard, not a comprehensive secret scanner.
"""
import argparse,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BLOCKED_DIRS={'data','backups','exports','.venv','venv','node_modules','__pycache__','.claude','.codex'}
BLOCKED_SUFFIXES={'.db','.sqlite','.sqlite3','.pem','.key','.p12','.log','.pyc'}
PATTERNS=[re.compile(rb'AIza[0-9A-Za-z_-]{35}'),re.compile(rb'gh[pousr]_[A-Za-z0-9]{30,}'),
          re.compile(rb'sk-ant-[A-Za-z0-9_-]{20,}'),re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
          re.compile(rb'/' + rb'Users/(?!YOUR_USERNAME(?:/|\b))[^/\s<>]+/'),re.compile(rb'/' + rb'home/(?!YOUR_USERNAME(?:/|\b))[^/\s<>]+/')]
def check(name,blob):
    path=Path(name)
    if set(path.parts)&BLOCKED_DIRS or path.suffix in BLOCKED_SUFFIXES or path.name.startswith('.env') and path.name!='.env.example' or path.name=='.mcp.json' or '.sqlite' in path.name:
        return 'sensitive/generated path'
    if len(blob)>1_000_000:return 'unexpected large file'
    if b'\x00' in blob:return 'unexpected binary file'
    if any(pattern.search(blob) for pattern in PATTERNS):return 'credential or personal-home-path pattern'
    return None

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--history',action='store_true');args=parser.parse_args()
    if args.history:
        paths={}
        for line in subprocess.check_output(['git','rev-list','--objects','--all'],cwd=ROOT,text=True).splitlines():
            oid,_,name=line.partition(' ')
            if name and subprocess.check_output(['git','cat-file','-t',oid],cwd=ROOT,text=True).strip()=='blob':paths[oid]=name
        entries=[(name,subprocess.check_output(['git','cat-file','blob',oid],cwd=ROOT)) for oid,name in paths.items()]
    else:
        # For a staged release this includes all nonignored source, even before git init.
        entries=[(str(p.relative_to(ROOT)),p.read_bytes()) for p in ROOT.rglob('*') if p.is_file() and not set(p.relative_to(ROOT).parts)&{'.git','.venv','__pycache__'}]
    errors=[f'{name}: {reason}' for name,blob in entries if (reason:=check(name,blob))]
    if errors:print('\n'.join(errors));return 1
    print(f'Release privacy guard passed: {len(entries)} files/blobs.');return 0
if __name__=='__main__':sys.exit(main())
