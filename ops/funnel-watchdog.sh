#!/usr/bin/env bash
# Tailscale Funnel watchdog for the public Dive Analyzer URL.
# Scheduled by ops/systemd/dive-funnel-watchdog.timer (installation is an
# explicit operational step: ops/tailscale/README.md).
#
# After an internet drop, tailscaled reconnects the tailnet on its own but the
# public Funnel ingress can stay dead until Funnel is re-announced
# (2026-10-26: ~35 min outage, fixed by `funnel off` + `funnel --bg`).
#
# One run = one small public request (the static /login page), resolved via
# public DoH so it takes the real internet path instead of MagicDNS. Repairs
# are escalating and rate-limited, then the watchdog gives up and only waits
# for recovery:
#   2 consecutive failures -> re-announce Funnel
#   still down 15 min later -> restart tailscaled, re-announce Funnel
#   still down 15 min later -> stop repairing, notify once
# Nothing is repaired while the server has no internet at all.
set -euo pipefail

PUBLIC_URL="${PUBLIC_URL:-https://dive-analyser.tail32dd14.ts.net/login}"
FUNNEL_TARGET="${FUNNEL_TARGET:-http://127.0.0.1:6091}"
DOH_URL="${DOH_URL:-https://1.1.1.1/dns-query}"
STATE_DIR="${STATE_DIR:-/var/lib/dive-funnel-watchdog}"
FAILS_BEFORE_REPAIR=2
REPAIR_SETTLE_SECONDS=900

mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/lock"
flock -n 9 || exit 0

read_state() { cat "$STATE_DIR/$1" 2>/dev/null || echo "${2:-0}"; }
write_state() { echo "$2" >"$STATE_DIR/$1"; }
log() { echo "funnel-watchdog: $*"; }

notify() {
    log "$1"
    if [[ -z "${TELEGRAM_BOT_TOKEN:-}" || -z "${TELEGRAM_CHAT_ID:-}" ]]; then
        return 0
    fi
    curl -sS -o /dev/null --max-time 15 \
        "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
        --data-urlencode "chat_id=${TELEGRAM_CHAT_ID}" \
        --data-urlencode "text=$1" || log "telegram notification failed"
}

probe() {
    local code
    code=$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
        --doh-url "$DOH_URL" "$PUBLIC_URL" 2>/dev/null) || true
    [[ "$code" == 200 ]]
}

internet_up() {
    curl -sS -o /dev/null --max-time 10 https://controlplane.tailscale.com/ 2>/dev/null
}

reannounce_funnel() {
    tailscale funnel --https=443 off >/dev/null 2>&1 || true
    tailscale funnel --bg --yes --https=443 "$FUNNEL_TARGET" >/dev/null
}

now=$(date +%s)
fails=$(read_state fails)
repairs=$(read_state repairs)
last_repair=$(read_state last_repair)
down_since=$(read_state down_since)

if probe; then
    if ((repairs > 0)); then
        notify "Dive Analyzer is public again (down ~$(((now - down_since) / 60)) min, $repairs repair(s))."
    fi
    rm -f "$STATE_DIR"/{fails,repairs,last_repair,down_since}
    exit 0
fi

if ! internet_up; then
    log "public URL down but server has no internet; waiting"
    exit 0
fi

((fails == 0)) && write_state down_since "$now" && down_since=$now
fails=$((fails + 1))
write_state fails "$fails"
log "public URL probe failed ($fails in a row)"

((fails < FAILS_BEFORE_REPAIR)) && exit 0
((now - last_repair < REPAIR_SETTLE_SECONDS)) && exit 0

down_min=$(((now - down_since) / 60))
case "$repairs" in
0)
    reannounce_funnel
    notify "Dive Analyzer public URL down ~${down_min} min. Re-announced Tailscale Funnel."
    ;;
1)
    systemctl restart tailscaled
    sleep 20
    reannounce_funnel
    notify "Dive Analyzer still down after Funnel re-announce (~${down_min} min). Restarted tailscaled."
    ;;
2)
    notify "Dive Analyzer still down after restarting tailscaled (~${down_min} min). Watchdog stopped repairing; check: sudo tailscale funnel status, docker ps."
    ;;
*)
    exit 0
    ;;
esac
write_state repairs $((repairs + 1))
write_state last_repair "$now"
