#!/usr/bin/env python3
"""Create a consistent SQLite snapshot without interrupting the local server."""
import argparse, sqlite3
from pathlib import Path
from server import ROOT, default_db
p=argparse.ArgumentParser();p.add_argument('destination');p.add_argument('--db',default=default_db());a=p.parse_args()
source=Path(a.db).resolve();destination=Path(a.destination).expanduser().resolve()
if not source.is_file():p.error('Source database does not exist.')
if destination.exists():p.error('Destination already exists; choose a new path.')
destination.parent.mkdir(parents=True,exist_ok=True)
# Reserve the destination atomically before opening it through SQLite.
with destination.open('xb'):pass
try:
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(destination) as dst:src.backup(dst)
except Exception:
    destination.unlink(missing_ok=True);raise
print(f'Backup saved: {destination}')
