# EXTERNAL_ACCESS_V1 — external ingress architecture and P8 audit

> Status after `MEDIA_BACKBONE_P8_ACCELERATED_PRODUCTIONIZATION_V1`:
> **EXTERNAL_ACCESS_PROVIDER_GATE** — the app is LAN_ONLY today; external
> athlete access is possible but requires exactly ONE consolidated
> human/provider action (§6). No port-forwarding was performed or
> approved in P8.

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
| Other tunnels | cloudflared exists but serves navidrome only (service inactive); ZeroTier present (not used for this app) |
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
  (still auth-gated). Safe.
- `USER_AUTH_ENABLED=false` → UNAUTHENTICATED legacy access. Under any
  public ingress this is NOT an acceptable routine rollback — it must
  be treated as an emergency state (e.g. disable the tunnel first).
  Documented here as the standing rule.

## 6. THE one HUMAN/PROVIDER action (when external access is wanted)

    HUMAN_PROVIDER_ACTION (single, consolidated):
      In the Cloudflare dashboard: choose/point a subdomain (e.g.
      dive.<family-domain>) and create a Zero-Trust tunnel route for
      `https://<subdomain>` → `http://<server>:6443` (or the nginx
      container), then add that hostname to CORS_ALLOW_ORIGINS on the
      server and reload nginx.
    Everything on the machine side is already prepared; P8 performed
    NONE of this action.
