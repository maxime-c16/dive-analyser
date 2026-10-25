"""Guard: no route runs synchronous SQL on the event loop.

An ``async def`` handler executes on the event loop, so its synchronous
SQLAlchemy calls block it. When a Library burst exhausts the connection
pool, the pool wait froze the whole process for ~30 s; requests already
holding a connection sat "idle in transaction" until PostgreSQL killed them
(idle_in_transaction_session_timeout=30s) -> 500s on /auth/me and media.
A handler that takes ``db`` and never awaits must be a plain ``def`` so
FastAPI runs it in the thread pool.
"""
import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
API = APP / "api"
ROUTE_METHODS = {"get", "post", "put", "patch", "delete", "api_route"}


def _offenders():
    for path in sorted(API.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            if "db" not in [a.arg for a in node.args.args + node.args.kwonlyargs]:
                continue
            if not any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") in ROUTE_METHODS
                       for d in node.decorator_list):
                continue
            if any(isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for x in ast.walk(node)):
                continue
            yield f"{path.relative_to(API)}:{node.lineno} {node.name}"


def test_db_routes_without_await_are_sync():
    assert list(_offenders()) == []


def test_no_async_db_function_without_await_anywhere():
    """Dependencies too: the global member_access_context ran blocking SQL
    on the loop for every request (async generator, no await)."""
    offenders = []
    for path in sorted(APP.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.AsyncFunctionDef)
                    and "db" in [a.arg for a in node.args.args + node.args.kwonlyargs]
                    and not any(isinstance(x, (ast.Await, ast.AsyncFor, ast.AsyncWith)) for x in ast.walk(node))):
                offenders.append(f"{path.relative_to(APP)}:{node.lineno} {node.name}")
    assert offenders == []
