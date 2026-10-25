"""Controlled repro: advisory xact lock taken on the event loop by GET status.

Mirrors production versions (fastapi 0.104.1, starlette 0.27, sqlalchemy
2.0.23, psycopg2, one uvicorn worker) and the production shapes:
  - get_db: sync generator, rollback+close in teardown (app/database.py)
  - router dependency: async def, sync SELECT (member_access_context)
  - GET /status/{n}: async def; reclaim_expired_media_jobs ->
      SELECT pg_advisory_xact_lock(73125, 1); no commit (like _status_for_asset)
  - POST /lease: async def; same lock, then commit (like /media/jobs/lease)
A throwaway local Postgres is required (DSN argument). Its
idle_in_transaction_session_timeout plays the role of production's 30 s.

Integration regression: backend/tests/test_postgres_media_startup_lot1.py uses
the real status and lease handlers, asserts <1s and checks the PG log.

Variants:
  today       : as above
  threadpool  : /status and /lease as `def` (Starlette threadpool)
  no_reclaim  : /status without the advisory lock (read-only status path)
Each round fires N status requests + 1 lease concurrently.
"""
import argparse, asyncio, json, statistics, threading, time

import httpx, uvicorn
from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

ap = argparse.ArgumentParser()
ap.add_argument("dsn")
ap.add_argument("--n", type=int, default=3)
ap.add_argument("--rounds", type=int, default=6)
ap.add_argument("--port", type=int, default=18800)
ap.add_argument("--no-lease", action="store_true", help="user status requests only")
ap.add_argument("--variants", default="today,threadpool,no_reclaim")
args = ap.parse_args()

engine = create_engine(args.dsn, pool_size=10, max_overflow=2, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        try:
            db.rollback()
        except Exception:
            pass
        db.close()


def build(variant):
    async def member_access_context(db=Depends(get_db)):
        db.execute(text("SELECT 1"))  # session + diver lookups
        yield

    if variant == "fixed":
        def member_access_context(db=Depends(get_db)):
            db.execute(text("SELECT 1"))
            yield

    router = APIRouter(dependencies=[Depends(member_access_context)])

    def status_body(db, n):
        if variant not in {"no_reclaim", "fixed"}:
            db.execute(text("SELECT pg_advisory_xact_lock(73125, 1)"))
        db.execute(text("SELECT pg_sleep(0.002)"))
        return {"n": n}

    def lease_body(db):
        db.execute(text("SELECT pg_advisory_xact_lock(73125, 1)"))
        db.commit()
        return {"jobs": []}

    if variant in {"threadpool", "fixed"}:
        @router.get("/status/{n}")
        def status(n: int, db=Depends(get_db)):
            return status_body(db, n)

        @router.post("/lease")
        def lease(db=Depends(get_db)):
            return lease_body(db)
    else:
        @router.get("/status/{n}")
        async def status(n: int, db=Depends(get_db)):
            return status_body(db, n)

        @router.post("/lease")
        async def lease(db=Depends(get_db)):
            return lease_body(db)

    app = FastAPI()
    app.include_router(router)
    return app


async def burst(port, n):
    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=60) as client:
        t0 = time.perf_counter()

        async def one(method, path):
            try:
                r = await client.request(method, path)
                code = r.status_code
            except Exception as exc:
                code = type(exc).__name__
            return path, code, round((time.perf_counter() - t0) * 1000)
        tasks = [one("GET", f"/status/{i}") for i in range(n)] + ([] if args.no_lease else [one("POST", "/lease")])
        return await asyncio.gather(*tasks)


def run(variant, port):
    server = uvicorn.Server(uvicorn.Config(build(variant), port=port, log_level="critical"))
    th = threading.Thread(target=server.run, daemon=True); th.start()
    deadline = time.time() + 10
    while not server.started:
        if not th.is_alive() or time.time() > deadline: raise SystemExit("server failed")
        time.sleep(0.02)
    rounds = []
    for _ in range(args.rounds):
        rounds.append(asyncio.run(burst(port, args.n)))
        time.sleep(0.2)
    server.should_exit = True; th.join()
    worst = [max(ms for _, _, ms in r) for r in rounds]
    errors = sum(1 for r in rounds for _, code, _ in r if code != 200)
    return {"variant": variant, "rounds": args.rounds, "requests_per_round": args.n + (0 if args.no_lease else 1),
            "worst_ms_per_round": worst, "median_worst_ms": statistics.median(worst),
            "rounds_over_1s": sum(w > 1000 for w in worst), "non_200": errors}


with engine.connect() as c:
    idle = c.execute(text("show idle_in_transaction_session_timeout")).scalar()
out = {"idle_in_transaction_session_timeout": idle, "results": []}
for k, v in enumerate(args.variants.split(",")):
    out["results"].append(run(v, args.port + k))
print(json.dumps(out, indent=2))
