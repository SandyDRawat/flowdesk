#!/bin/zsh
cd -- "$(dirname -- "$0")"
if [[ -f "$HOME/Library/LaunchAgents/local.flowdesk.plist" ]]; then
    python3 service.py start || exit 1
    /usr/bin/open 'http://127.0.0.1:8765/'
else
    python3 server.py --open
fi
