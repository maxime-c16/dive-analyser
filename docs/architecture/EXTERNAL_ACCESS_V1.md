# EXTERNAL_ACCESS_V1 — external ingress architecture and P8/P9 audit

> Status after `MEDIA_BACKBONE_P9_PRODUCTION_READINESS_AND_EXTERNAL_ACCESS_V1`:
> **EXTERNAL_ACCESS_PROVIDER_GATE** — the app remains LAN_ONLY; every
> machine-side preparation is DONE and live-tested end-to-end through a
> temporary Cloudflare quick tunnel; external access now requires exactly
> ONE consolidated human/provider action (§7). No port-forwarding was
> performed or approved in P8 or P9.

## 1. Fresh topology audit (2026-09-10)

| Layer | Finding |
|---|---|
| Server | Debian 12, `deb-serv` @ 192.168.1.57 |
| nginx | docker, binds `0.0.0.0:6090` (HTTP) + `0.0.0.0:6443` (HTTPS, internal CA); SPA + `/api/` proxy |
| Backend | loopback-only `127.0.0.1:6002` |
| Postgres / adminer | loopback-only (127.0.0.1:5433 / :8080) |
| Host firewall | INPUT policy ACCEPT (no restrictive rules) |
| Router/NAT | NO port-forward for 6090/6443 (WAN probe dead); public IPv4 is the VPN exit IP |
| IPv6 | Provider-delegated prefix; no dive-analyser ingress published |
| TLS | HTTPS on 6443 (nginx, internal CA) — HTTP 6090 remains LAN-only |
| Other tunnels | cloudflared exists as `cloudflared-navidrome.service`: an EPHEMERAL QUICK TUNNEL (`--url http://127.0.0.1:4533`, no config file, no credentials, no owned hostname) for Navidrome only; service inactive-ish but running. ZeroTier present (not used for this app) |
| Owned DNS | DuckDNS `mcauchysmontreuil.duckdns.org` (A-record updater) — DuckDNS cannot host the `cfargotunnel.com` CNAME a named tunnel needs, and duckdns.org is not a zone in the Cloudflare account. No owned domain in Cloudflare. |
| Session cookie | HttpOnly + Secure + SameSite=Strict (unchanged; Secure never weakened) |

Classification: **LAN_ONLY**.

## 2. Security invariants for ANY external exposure

1. HTTPS mandatory (never raw 6090).
2. Auth required for every media route; the unauthenticated historical
   mode is EMERGENCY-ONLY and must never be combined with public ingress.
3. Session cookie stays HttpOnly/Secure/SameSite=Strict.
4. Proxy trust: the login rate limiter derives client IP from
   X-Forwarded-For only as appended by the trusted nginx hop (first
   element = nginx-observed peer; caller-supplied chain elements are
   ignored). A NEW tunnel/proxy in front of nginx must keep this
   property: exactly one trusted proxy boundary, no arbitrary caller
   XFF trust.
5. Origin validation: P8 fixed nginx to forward `$http_host`
   (port-preserving) so the backend can reconstruct same-origin
   candidates. An external hostname must be added to
   `CORS_ALLOW_ORIGINS` (no wildcards).
6. B2 CORS: NOT required — playback stays same-origin route → 302 → B2
   (proved in P5/P6). Do not add B2 CORS rules without new evidence.
7. Error disclosure: uniform 401/404 denials (no ownership or existence
   oracles); storage identities, bucket names, internal paths and stack
   traces never in external responses.

## 3. Option families evaluated (evidence-based)

- **Cloudflare Tunnel (Zero-Trust)** — RECOMMENDED for external athlete
  access: no router changes, no inbound ports, TLS terminates at
  Cloudflare, browser-native (no client installs), existing cloudflared
  binary on the host, free tier sufficient. Fits non-technical athletes.
- **Tailscale / identity-aware VPN** — technically clean but requires a
  client on every athlete device; unsuitable for normal non-technical
  athletes as a primary path. Good as an OPERATOR path.
- **Raw router port-forward → nginx** — REJECTED as an architecture
  absent a dedicated security design (packet §16).
- **Managed reverse proxy** — equivalent outcome to a tunnel with more
  moving parts; not needed.

## 4. Required code/config preparation (DONE or READY in P8)

- Origin/CSRF: `$http_host` fix live; adding an external hostname =
  one `CORS_ALLOW_ORIGINS` entry + tunnel hostname config.
- Proxy trust: unchanged and compatible (nginx remains the trusted
  boundary; cloudflared → nginx → backend).
- X-Forwarded-Proto: nginx already forwards it; backend uses it in
  origin candidates.
- Metrics/audit trail now exist for external-era observability.

## 5. Rollback semantics under external access

- `B2_PLAYBACK_CANARY_ENABLED=false` → authenticated legacy fallback
  (still auth-gated). Safe. REVALIDATED LIVE in P9 through the real nginx
  (play route fail-closed 404; authenticated legacy video 307→200 with
  Range 206; unauth 401) and re-armed after the proof.
- `USER_AUTH_ENABLED=false` → UNAUTHENTICATED legacy access. Under any
  public ingress this is NOT an acceptable routine rollback — it must
  be treated as an emergency state (e.g. disable the tunnel first).
  Documented here as the standing rule.

## 6. P9 external-path evidence (temporary quick tunnel, real internet)

To test the exact external path without the owned-domain gate, P9 ran a
SHORT-LIVED Cloudflare quick tunnel (`cloudflared tunnel --url
http://127.0.0.1:6002`, random trycloudflare hostname) for ~25 minutes,
then terminated it (verified dead: HTTP 530). From a genuinely external
client over the internet:

- login with exact-origin → 200; cookie `HttpOnly + Secure + SameSite=Strict + Path=/`;
  foreign Origin → 403; wrong password → uniform 401
- unauthenticated: B2 play 401, legacy video 401, legacy check 401, me 401
- authenticated wrong-owner: B2 play 404, legacy video 404, legacy cache
  play 404 (uniform `{"detail":"Not found"}` — no existence/ownership oracle)
- authenticated owner: play → 302 presigned B2 URL; provider ranged GET
  206 (`Content-Range: bytes 0-65535/21601174`, `video/quicktime`);
  seek range (1 MB–2 MB) 206; expired presign after TTL → provider 401,
  fresh grant → 302 → 206 (refresh cycle proven externally)
- 15 external-path playback grants per pass, all 302, zero leaks
- error privacy: JSON error bodies (401/403/404/422) contain no filesystem
  paths, no bucket/object keys (bucket+key appear ONLY in the by-design
  presigned redirect Location), no stack traces, no other-diver identity;
  `Cache-Control: private, no-store`, `Referrer-Policy: no-referrer`,
  `X-Content-Type-Options: nosniff` on auth/play responses
- proxy trust: client-IP rate-limit identity anchored to the
  trusted-ingress XFF first element (unit-tested: appended caller-supplied
  chain elements cannot forge the bucket; correct password still capped)
- browser-level (Chrome/WebKit) external runs were not feasible before the
  stable hostname exists; the same routes were browser-proven on LAN in
  P6 (Chromium + WebKit). Browser-level external verification is part of
  the post-provider-action checklist below.

## 7. THE one HUMAN/PROVIDER action (when external access is wanted)

    HUMAN_PROVIDER_ACTION (single, consolidated):

    ACTION:
      1. Provide a domain zone in the Cloudflare account (buy/register or
         transfer an existing domain; DuckDNS cannot be used — it cannot
         host the required cfargotunnel.com CNAME and is not a CF zone).
      2. In the Cloudflare Zero Trust dashboard: Networks → Tunnels →
         Create a tunnel → type "Cloudflared" → name it `diveanalyzer`
         → install the connector on deb-serv (Debian 64-bit .deb or the
         shown docker command; the host already has cloudflared 2026.6.1)
         → in the tunnel's "Public Hostname" tab add:
         subdomain=dive, domain=<your-domain>,
         service=HTTP, URL=localhost:6091
      3. Report back the resulting hostname; the machine-side activation
         (external vhost + CORS entry + systemd unit) is then applied and
         re-verified (login/playback/IDOR + Chrome/WebKit externally).

    EXACT_UI_LOCATION:
      Cloudflare Dashboard → Zero Trust → Networks → Tunnels →
      "Create a tunnel" → connector tab → Public Hostname tab.

    HOSTNAME:
      dive.<your-domain>   (exact hostname chosen here must be reported)

    VALUES:
      Tunnel name: diveanalyzer
      Service:     HTTP localhost:6091
      (nothing else needs filling; leave HTTP settings defaults)

    DO_NOT_CHANGE:
      - cloudflared-navidrome.service and its quick tunnel (different app)
      - no router/NAT/port-forward changes anywhere
      - no Cloudflare Access policy on the app paths in this step
        (the app's own AppUser auth is the authentication layer; Access
        may be evaluated separately later)
      - no B2/CORS changes on Backblaze (playback is same-origin 302)
      - never enable the raw LAN nginx 6090/6443 for WAN exposure

## 8. Machine-side prepared artifacts (P9, committed, NOT enabled)

- `ops/cloudflared/diveanalyzer-tunnel.yml` — named-tunnel config
  (ingress: `dive.<domain>` → `http://localhost:6091`, catch-all 502)
- `ops/cloudflared/diveanalyzer-tunnel.service` — systemd unit (enable only
  after the provider action; separate from the navidrome service)
- `nginx/conf.d/external.conf.example` — loopback-only `127.0.0.1:6091`
  vhost: SPA + API only, `/adminer/` explicitly refused, `Host $http_host`
  preserved, trusted-proxy chain unchanged
- Activation checklist (after the human action): deploy the vhost with the
  real hostname → add `https://dive.<domain>` to `CORS_ALLOW_ORIGINS`
  (exact, no wildcard) → `nginx -t` + reload → enable the systemd unit →
  external tests: login, /auth/me, play 302→206, Range/seek, expired
  presign refresh, unauth/wrong-owner/foreign-origin denials, error-privacy
  sweep, Chrome + WebKit playback.

## 9. Same tunnel vs separate tunnel (decision)

SEPARATE NAMED TUNNEL for Dive Analyzer. The existing cloudflared is an
ephemeral quick tunnel with NO config/credentials/ownership on the host;
sharing it would mean owning the Navidrome service and an unstable random
hostname. A named `diveanalyzer` tunnel has its own credential file, its
own ingress, and can be disabled without touching Navidrome. Smallest safe
change on the machine: one extra systemd unit + one loopback vhost.
