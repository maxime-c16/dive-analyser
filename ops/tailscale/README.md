# Dive Analyzer public access

Activated on 2026-10-04 at:

**https://dive-analyser.tail32dd14.ts.net/**

Tailscale Funnel provides HTTPS and a stable hostname on the free Personal
plan. Visitors need a browser and either an existing Dive Analyzer account
or a shared-video link;
they do not need Tailscale or WireGuard. The server must remain online.
Funnel has provider bandwidth limits. B2 playback redirects send video bytes
directly from B2 to the viewer.

## Deployment

The dedicated proxy runs as `dive-funnel-funnel-proxy-1`, using the files
under `/home/mcauchy/dive-analyser/ops/tailscale`. It joins the existing
`diving_network` and publishes **only** `127.0.0.1:6091` on the host.
The separate LAN proxy and WireGuard configuration remain in use.

```sh
docker-compose -p dive-funnel -f ops/tailscale/docker-compose.yml up -d
sudo tailscale funnel --bg --yes http://127.0.0.1:6091
```

`tailscaled` is enabled at boot, Funnel's `--bg` configuration persists,
and the proxy has Docker's `unless-stopped` restart policy. Tailscale
accepts neither DNS configuration nor advertised subnet routes, and does
not provide Tailscale SSH or an exit node.

The backend runtime `.env` includes
`https://dive-analyser.tail32dd14.ts.net` in `CORS_ALLOW_ORIGINS`.
`USER_AUTH_ENABLED=true` and secure session cookies must stay enabled.

External API routes require an active session via nginx `auth_request`,
except the authentication/registration endpoints, `/api/v1/shared-dives/` and the
two magic-link claim calls (`/api/v1/deposits/claim/peek|redeem`).
The `/claim` landing page is public as well: its single-use token lives in the
URL fragment and is exchanged for a normal session on an explicit button press.
The `/share/` page is also public: its URL-fragment secret is exchanged for
a guest grant, which the backend validates for each shared-video request.
An invalid or revoked link grants no access. This also protects historical
analytics endpoints without backend session dependencies. Media ownership
authorization remains enforced by the backend. Database Adminer and API
documentation are refused on the public proxy. Caller-supplied forwarding
headers are discarded; IP login limits share the local connector's bucket,
in addition to the existing per-account limits.

After recreating backend or frontend containers, reload this proxy so nginx
resolves their current Docker addresses:

```sh
docker exec dive-funnel-funnel-proxy-1 nginx -t
docker exec dive-funnel-funnel-proxy-1 nginx -s reload
```

## Funnel watchdog

After an internet drop, tailscaled reconnects the tailnet by itself but the
public Funnel ingress can stay dead until Funnel is re-announced
(2026-10-26: ~35 min outage). `ops/funnel-watchdog.sh` runs every 5 minutes
from `ops/systemd/dive-funnel-watchdog.timer`: one request to the static
`/login` page, resolved through public DoH so it takes the real internet path
(a MagicDNS lookup from the server itself is not a valid public test). After
2 failures in a row it re-announces Funnel; 15 minutes later, if still down,
it restarts tailscaled; 15 minutes after that it stops repairing. It never
repairs while the server has no internet. Every repair, the give-up and the
recovery are sent to Telegram through the server alerts bot.

Install once (as root on deb-serv). The token comes from the alertmanager
swarm secret, so it is never typed or printed:

```sh
umask 077
{ printf 'TELEGRAM_BOT_TOKEN='
  docker exec "$(docker ps -q -f name=server-alertmanager)" cat /run/secrets/server_telegram_bot_token
  printf '\nTELEGRAM_CHAT_ID=8543543707\n'; } >/etc/dive-funnel-watchdog.env
cp ops/systemd/dive-funnel-watchdog.{service,timer} /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dive-funnel-watchdog.timer
```

Status: `journalctl -u dive-funnel-watchdog -n 20`. State (consecutive
failures, repairs) lives in `/var/lib/dive-funnel-watchdog`.

## Account maintenance

Key expiry for `dive-analyser` was disabled in the Tailscale Machines
dashboard and verified on 2026-10-04 (`Self.KeyExpiry` is null), so periodic
server reauthentication is not required. The provider account controls
this setting.

Friends need app accounts provisioned through the existing operator CLI:

```sh
docker exec -it dive-analyser-backend-1 python scripts/manage_user.py create-user --email FRIEND_EMAIL --diver-id DIVER_ID
```

The CLI prompts securely for a password. Bind only the intended diver's
media. Existing analytics metadata is shared among authenticated app users;
this proxy adds a login gate, not per-user filtering to analytics.

## Verification and shutdown

Public HTTPS login page was checked in the collaborative browser.
Anonymous data requests return 401, unauthenticated navigation redirects
to `/login`, foreign-origin login returns 403, and Adminer/docs return 404.
Authenticated identity, library and analytics requests were checked using
a short-lived verification session, revoked afterward without invalidating
existing sessions.
An authorized video playback grant returned 302, its signed B2 URL served
a 65,536-byte range with HTTP 206, and anonymous access to the same playback
endpoint returned 401. Full authenticated browser playback was not tested.

Inspect public access with `sudo tailscale funnel status`. Stop only this
public endpoint with:

```sh
sudo tailscale funnel --https=443 off
```

Disable Funnel **before** ever turning off backend user authentication.
The existing Cloudflare artifacts and architecture audit are historical
preparation; Funnel removes the need for their owned-domain provider step.

To check guest routing without creating a grant or accessing a video:

```sh
python3 ops/tailscale/check_guest_routes.py https://dive-analyser.tail32dd14.ts.net
```

After changing this proxy configuration, deploy with `ci/ship.sh` and recreate
the Funnel proxy as described in `docs/REPO_WORKFLOW.md`.
