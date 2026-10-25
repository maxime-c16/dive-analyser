import json, subprocess, time, sys
B = "https://dive-analyser.tail32dd14.ts.net"
def curl(url, cookie=True, rng=None):
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{json}"]
    if cookie: cmd += ["-H", "@ch.txt"]
    if rng: cmd += ["-H", f"Range: bytes={rng}"]
    return json.loads(subprocess.run(cmd + [url], capture_output=True, text=True).stdout)
def status(u):
    r = subprocess.run(["curl", "-s", "-H", "@ch.txt", "-w", "\n%{time_total}", f"{B}/api/v1/media/{u}/status"], capture_output=True, text=True).stdout
    body, t = r.rsplit("\n", 1); return json.loads(body), float(t)
items = json.load(open("lib.json"))["items"]
want = {"d5_light": 4, "legacy_preview": 4}; rows = []
for it in items[:80]:
    if all(v <= 0 for v in want.values()): break
    st, ts = status(it["video_uuid"])
    light = ((st.get("derivatives") or {}).get("light") or {})
    if light.get("state") == "ready" and light.get("playback_url"): kind, url = "d5_light", light["playback_url"]
    elif st.get("preview_url"): kind, url = "legacy_preview", st["preview_url"]
    else: continue
    if want[kind] <= 0: continue
    want[kind] -= 1
    first = curl(B + url, rng="0-1048575")
    row = {"kind": kind, "status_s": ts, "first_code": first["http_code"], "first_ttfb_s": first["time_starttransfer"], "first_total_s": first["time_total"], "first_bytes": first["size_download"]}
    if first["http_code"] == 302:
        b2 = curl(first["redirect_url"], cookie=False, rng="0-1048575")
        row.update({"b2_code": b2["http_code"], "b2_tls_s": b2["time_appconnect"], "b2_ttfb_s": b2["time_starttransfer"], "b2_total_s": b2["time_total"], "b2_bytes": b2["size_download"]})
        row["click_to_1MiB_s"] = round(ts + first["time_total"] + b2["time_total"], 3)
    else:
        row["click_to_1MiB_s"] = round(ts + first["time_total"], 3)
    rows.append(row); print(json.dumps(row)); time.sleep(2)
json.dump(rows, open("play-prod.json", "w"), indent=1)
