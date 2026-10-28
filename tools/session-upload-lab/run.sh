#!/usr/bin/env bash
# Start the session upload lab on the LAN. Prereq: b2_setup.py has written
# ~/.config/dive-analyser/session-lab.env.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
env_file="$HOME/.config/dive-analyser/session-lab.env"
venv="${SESSION_LAB_VENV:-/tmp/session-lab-venv}"
[ -f "$env_file" ] || { echo "missing $env_file — run b2_setup.py first" >&2; exit 1; }
[ -x "$venv/bin/python" ] || { uv venv -q "$venv" && uv pip install -q --python "$venv/bin/python" boto3; }
set -a; . "$env_file"; set +a
export SESSION_LAB_LAN_IP="${SESSION_LAB_LAN_IP:-$(ipconfig getifaddr en0 || ipconfig getifaddr en1)}"
token_file="$HOME/.config/dive-analyser/session-lab.token"
[ -f "$token_file" ] || (umask 077; python3 -c 'import secrets;print(secrets.token_urlsafe(9))' > "$token_file")
export SESSION_LAB_TOKEN="$(cat "$token_file")"
exec "$venv/bin/python" "$here/server.py"
