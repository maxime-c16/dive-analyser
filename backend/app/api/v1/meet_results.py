"""Official meet results on competition events (under the calendar gate).

Upload is the raw PDF body (Content-Type: application/pdf), read with a byte
budget before any parsing, then parsed and stored off the event loop. The
same file is sent twice: once to preview, once to save; the server parses it
each time, so the stored rows never come from client-side JSON.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy import inspect
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.api.v1.auth import get_current_user
from app.api.v1.calendar import admin_writer, calendar_gate, commit, private_responses, writer
from app.api.v1.admin_users import require_admin
from app.database import get_db
from app.models.user_auth import AppUser
from app.services import meet_results as service
from app.services.meet_results_pdf import MeetPdfError, parse_pdf

MAX_PDF_BYTES = 8 * 1024 * 1024
_schema_ready = False


def results_gate(db: Session = Depends(get_db)) -> None:
    global _schema_ready
    if not _schema_ready:
        if not inspect(db.get_bind()).has_table("meet_result_dives"):
            raise HTTPException(503, "Meet results schema not installed")
        _schema_ready = True


router = APIRouter(prefix="/calendar", dependencies=[Depends(calendar_gate), Depends(results_gate),
                                                    Depends(private_responses)])


async def _pdf_body(request: Request) -> bytes:
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_PDF_BYTES:
            raise HTTPException(413, detail={"code": "too_large", "message": "The PDF must be at most 8 MB"})
        chunks.append(chunk)
    return b"".join(chunks)


def _parse(raw: bytes):
    try:
        return parse_pdf(raw)
    except MeetPdfError as exc:
        raise HTTPException(422, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("/events/{event_id}/results")
def get_results(event_id: int, summary: bool = False, user: AppUser = Depends(get_current_user),
                db: Session = Depends(get_db)):
    return service.read(db, user, event_id, summary)


@router.post("/events/{event_id}/results/preview")
async def preview_results(event_id: int, request: Request, user: AppUser = Depends(writer),
                          db: Session = Depends(get_db)):
    raw = await _pdf_body(request)

    def run():
        return service.preview(db, user, event_id, _parse(raw))
    return await run_in_threadpool(run)


@router.put("/events/{event_id}/results")
async def save_results(event_id: int, request: Request, name: str = Query("", max_length=200),
                       user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    raw = await _pdf_body(request)

    def run():
        service.replace(db, user, event_id, _parse(raw), name, raw)
        commit(db)
        return service.read(db, user, event_id)
    return await run_in_threadpool(run)


@router.delete("/events/{event_id}/results", status_code=204)
def delete_results(event_id: int, user: AppUser = Depends(writer), db: Session = Depends(get_db)):
    service.delete(db, user, event_id)
    commit(db)
    return Response(status_code=204)


# --- Administrators: who is tied to whom -------------------------------------------

class LinkWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: Optional[int]  # null = never link this person


@router.get("/admin/meet-accounts")
def meet_accounts(q: str = Query(..., min_length=2, max_length=60), admin: AppUser = Depends(require_admin),
                  db: Session = Depends(get_db)):
    return {"items": service.account_candidates(db, q)}


@router.put("/results/entries/{entry_id}/link", status_code=204)
def set_link(entry_id: int, payload: LinkWrite, admin: AppUser = Depends(admin_writer), db: Session = Depends(get_db)):
    """Tie this person to an account (or never link them) in every meet."""
    service.set_link(db, admin, entry_id, payload.user_id)
    commit(db)
    return Response(status_code=204)


@router.delete("/results/entries/{entry_id}/link", status_code=204)
def clear_link(entry_id: int, admin: AppUser = Depends(admin_writer), db: Session = Depends(get_db)):
    """Back to automatic matching for this person."""
    service.clear_link(db, admin, entry_id)
    commit(db)
    return Response(status_code=204)
