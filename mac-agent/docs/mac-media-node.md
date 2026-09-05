# Dedicated Mac Media Node

## Architecture

`deb-serv` remains the production API, PostgreSQL, frontend, nginx, analytics,
job registry, representative registry, and durable poster/proxy cache. The
user-scoped worker on `mac-server.local` discovers Photos assets, selectively
recalls one UUID, validates source video, transcodes poster/proxy renditions,
and uploads them to Debian.

The production browser never receives a Mac filesystem path. Source identity
uses a canonical production UUID plus an agent-local Photos UUID. The
`cloud_guid`/Photos fingerprint links the two where it is unambiguous.

## Node Identity

- Agent ID: `mac-media-01`
- LAN: `mac-server.local`, wired `192.168.1.19`, Wi-Fi fallback `192.168.1.194`
- Wired adapter MAC: `f8:e4:3b:65:d3:5b`
- DHCP reservation required: MAC above to `192.168.1.19`
- Photos worker: user LaunchAgent `com.diveanalyzer.agent`
- Machine health/caffeinate: system LaunchDaemon

## Safety

The worker is limited to `max_jobs: 1`, `poster`, and `proxy_360p`.
`allow_original` and `allow_icloud_download` remain false. The separately named
single-asset materializer may invoke a one-UUID `--download-missing` export only
for the leased UUID. Full-library export, retry-all, and cache warming are not
part of this architecture.

## Current Gate

Do not enable leasing until both conditions hold:

1. The `divesensei` GUI session has completed the Photos privacy rehearsal and
   backend heartbeat reports `photos_access_status=ok`.
2. An APFS volume named `DiveSenseiMedia` is mounted and its recorded volume
   UUID matches the agent configuration.

