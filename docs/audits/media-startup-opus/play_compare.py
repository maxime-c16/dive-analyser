import json, subprocess, time
B = "https://dive-analyser.tail32dd14.ts.net"
def run(args): return subprocess.run(args, capture_output=True, text=True).stdout
def timed(url, cookie=True):
    a = ["curl", "-s", "-H", "Range: bytes=0-1048575", "-o", "/dev/null", "-w", "%{json}"] + (["-H", "@ch.txt"] if cookie else [])
    return json.loads(run(a + [url]))
items = json.load(open("lib.json"))["items"]; rows = []
for it in items[1:60:6]:
    st = json.loads(run(["curl", "-s", "-H", "@ch.txt", f"{B}/api/v1/media/{it['video_uuid']}/status"]))
    prev = next((e["playback_url"] for e in st.get("cache_entries") or [] if e["rendition"] == "proxy_720p"), None)
    light = ((st.get("derivatives") or {}).get("light") or {}).get("playback_url")
    if not (prev and light and "/media/cache/" in prev): continue
    p = timed(B + prev); time.sleep(1)
    g = timed(B + light); time.sleep(0.2)
    b = timed(g["redirect_url"], cookie=False) if g["http_code"] == 302 else {}
    row = {"local_proxy_total_s": p["time_total"], "local_proxy_bytes": p["size_download"],
           "d5_grant_s": g["time_total"], "d5_b2_ttfb_s": b.get("time_starttransfer"), "d5_b2_total_s": b.get("time_total"),
           "d5_total_s": round(g["time_total"] + (b.get("time_total") or 0), 3)}
    rows.append(row); print(json.dumps(row)); time.sleep(2)
    if len(rows) >= 5: break
json.dump(rows, open("play-compare-prod.json", "w"), indent=1)
