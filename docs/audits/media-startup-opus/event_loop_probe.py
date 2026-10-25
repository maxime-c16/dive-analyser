"""Controlled model: blocking SQL inside async FastAPI handlers/dependencies.

Not the production app. It reproduces the *shape* of the poster route
(`GET /api/v1/media/cache/{id}/play`) in one uvicorn worker:
  - router dependency `member_access_context` (async def, sync SQL) ~3 SELECTs
  - `require_legacy_media_user` + access chain ~4 SELECTs
  - `get_playable_entry` UPDATE last_accessed_at + COMMIT (WAL fdatasync)
Blocking waits are modelled with time.sleep (releases the GIL like a socket
wait). SELECT_MS and COMMIT_MS are parameters: COMMIT_MS defaults to the mean
sda flush latency measured on deb-serv over a 30 s window (39 ms).

Variants:
  async_blocking  : today's shape (everything on the event loop)
  threadpool      : same work in `def` handlers/deps (Starlette threadpool)
  async_noview    : today's shape but no per-view COMMIT

Usage: python event_loop_probe.py [--select-ms 1] [--commit-ms 39] [--n 15]
"""
import argparse, asyncio, json, statistics, threading, time

import httpx, uvicorn
from fastapi import Depends, FastAPI

ap = argparse.ArgumentParser()
ap.add_argument("--select-ms", type=float, default=1.0)
ap.add_argument("--commit-ms", type=float, default=39.0)
ap.add_argument("--n", type=int, default=15)
ap.add_argument("--port", type=int, default=18765)
args = ap.parse_args()
S, C = args.select_ms / 1000, args.commit_ms / 1000


def build(variant: str) -> FastAPI:
    if variant == "threadpool":
        def auth():
            time.sleep(3 * S)
        app = FastAPI(dependencies=[Depends(auth)])

        @app.get("/poster/{i}")
        def poster(i: int):
            time.sleep(4 * S + C)
            return {"i": i}

        @app.get("/me")
        def me():
            time.sleep(2 * S)
            return {}
    else:
        async def auth():
            time.sleep(3 * S)
        app = FastAPI(dependencies=[Depends(auth)])

        @app.get("/poster/{i}")
        async def poster(i: int):
            time.sleep(4 * S + (C if variant == "async_blocking" else 0))
            return {"i": i}

        @app.get("/me")
        async def me():
            time.sleep(2 * S)
            return {}
    return app


async def burst(port: int, n: int):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=30,
                                 limits=httpx.Limits(max_connections=n + 2)) as client:
        await client.get("/me")  # warm
        t0 = time.perf_counter()

        async def one(path):
            await client.get(path)
            return (time.perf_counter() - t0) * 1000
        posters = [asyncio.create_task(one(f"/poster/{i}")) for i in range(n)]
        await asyncio.sleep(0.005)
        me_ms = await one("/me")  # a light request arriving during the burst
        done = await asyncio.gather(*posters)
    return sorted(done), me_ms


def run(variant: str, port: int):
    server = uvicorn.Server(uvicorn.Config(build(variant), port=port, log_level="error", workers=1))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    deadline = time.time() + 10
    while not server.started:
        if not th.is_alive() or time.time() > deadline: raise SystemExit(f"server {variant} failed to start on {port}")
        time.sleep(0.02)
    rounds = [asyncio.run(burst(port, args.n)) for _ in range(5)]
    server.should_exit = True; th.join()
    last = [r[0][-1] for r in rounds]; med = [statistics.median(r[0]) for r in rounds]; me = [r[1] for r in rounds]
    return {"variant": variant, "posters": args.n,
            "last_poster_ms_median": round(statistics.median(last), 1),
            "median_poster_ms_median": round(statistics.median(med), 1),
            "me_during_burst_ms_median": round(statistics.median(me), 1)}


out = {"select_ms": args.select_ms, "commit_ms": args.commit_ms, "results": []}
for k, v in enumerate(["async_blocking", "threadpool", "async_noview"]):
    out["results"].append(run(v, args.port + k))
print(json.dumps(out, indent=2))
