# Session upload lab

Field test for step 1 of session sharing: the iPhone sends a raw session
video (several GB) **directly to B2** with a resumable multipart upload. The
Mac only signs one URL per chunk; no bytes go through deb-serv.

Isolated from production: dedicated private bucket `diveanalyzer-sessions`,
prefix `lab/`, files expire after 30 days, unfinished uploads are cancelled
after 3 days.

## Setup (once)

In the B2 console: create the private bucket `diveanalyzer-sessions`
(EU-Central), then an application key restricted to it (Read and Write, no
prefix). The web UI cannot create upload CORS rules, so:

```sh
python3 b2_setup.py --master-key-file <file "keyId:applicationKey"> \
  --origin http://192.168.1.151:8791
```

Sets the bucket private + browser CORS + lifecycle and writes the key to
`~/.config/dive-analyser/session-lab.env` (600). An account key also works
(it creates the bucket and mints a bucket-scoped key, never stored itself).
Re-run if the Mac's LAN IP changes (CORS origin).

## Run

```sh
./run.sh   # prints http://<mac-ip>:8791/?t=<token>
```

On the iPhone (same Wi-Fi): open the URL in Safari, then Share → Add to Home
Screen. The token is in the URL, so the PWA keeps it.

URL knobs: `&ps=<MiB>` part size (default 32), `&c=<n>` parallel parts
(default 4).

## What to test

1. Choose the video. In the picker, **Options → Format: Current**, otherwise
   iOS transcodes it before sending.
2. Leave the screen on (the page holds a wake lock), then try locking the
   screen, switching apps, switching Wi-Fi → 4G, airplane mode for 30 s.
3. Kill the PWA mid-upload, reopen it, and choose the same video again:
   parts already on B2 are skipped.
4. After "Vérifié sur B2 ✓", play and seek in the video (B2 playback).

Client + server events (part timings, errors, visibility, resume,
throughput) go to `~/Library/Logs/dive-session-lab/<date>.jsonl`.
