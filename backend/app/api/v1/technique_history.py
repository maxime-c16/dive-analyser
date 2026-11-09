"""Owner-only, revision fenced technique history. All handlers run in threadpool."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.diver import Diver
from app.models.dive import Dive
from app.models.technique_history import TechniqueTrack, Technique, TechniqueEpisode, TechniqueRevision
from app.services.write_guard import optional_session_user
from app.services.user_access import user_has_diver_access
from app.services.technique_history import FAMILIES
from app.services.technique_history_sql import RESOLVED, comparison_sql

router = APIRouter(prefix='/technique-history', tags=['technique-history'])


def owner(request, db, diver, lock=False):
    if lock:
        db.execute(select(Diver).where(Diver.id == diver).with_for_update()).scalar_one_or_none()
    user = optional_session_user(request, db)
    if user is None or not user.is_active or not user_has_diver_access(db, user.id, diver):
        raise HTTPException(403, 'Diver ownership required')
    return user


def track_for(db, diver, track, revision=None):
    stmt = select(TechniqueTrack).where(TechniqueTrack.id == track, TechniqueTrack.diver_id == diver)
    if revision is not None:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, 'Track not found')
    if revision is not None and row.revision != revision:
        raise HTTPException(409, 'History changed; refresh preview')
    return row


class TrackInput(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get('/{diver}/tracks')
def tracks(diver: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    owner(request, db, diver)
    rows = db.execute(select(TechniqueTrack).where(TechniqueTrack.diver_id == diver, TechniqueTrack.id > after).order_by(TechniqueTrack.id).limit(51)).scalars().all()
    return {'items': [{'id': r.id, 'name': r.name, 'revision': r.revision} for r in rows[:50]], 'next': rows[49].id if len(rows)>50 else None}


@router.post('/{diver}/tracks')
def create_track(diver: int, body: TrackInput, request: Request, db: Session = Depends(get_db)):
    owner(request, db, diver, True)
    if db.scalar(select(TechniqueTrack.id).where(TechniqueTrack.diver_id==diver, TechniqueTrack.name==body.name)):
        raise HTTPException(409, 'Track name exists')
    row = TechniqueTrack(diver_id=diver, name=body.name)
    db.add(row); db.commit()
    return {'id': row.id, 'name': row.name, 'revision': row.revision}


class ContextInput(BaseModel):
    code: str = Field(min_length=1, max_length=10)
    apparatus: str = Field(max_length=20)
    height: str = Field(max_length=5)
    position: str = Field(default='', max_length=1)
    sync: bool = False


class ReadInput(ContextInput):
    after: int = Field(default=0,ge=0)
    session_id:int | None = None
    from_date:datetime | None = None
    to_date:datetime | None = None


@router.post('/{diver}/{track}/attempts')
def attempts(diver: int, track: int, body: ReadInput, request: Request, db: Session = Depends(get_db)):
    owner(request, db, diver); row = track_for(db, diver, track)
    params = dict(body.model_dump(), diver=diver, track=track)
    rows = db.execute(text(RESOLVED + ' SELECT id,session_id,video_uuid,dive_code,dive_datetime,history_occurred_at,performance,episode_id,intended_id,state,use_id,source FROM resolved WHERE (CAST(:session_id AS integer) IS NULL OR session_id=:session_id) AND (CAST(:from_date AS timestamp) IS NULL OR history_occurred_at>=:from_date) AND (CAST(:to_date AS timestamp) IS NULL OR history_occurred_at<:to_date) AND (:after=0 OR (history_occurred_at,id)>(SELECT history_occurred_at,id FROM eligible WHERE id=:after)) ORDER BY history_occurred_at,id LIMIT 51'), params).mappings().all()
    return {'revision': row.revision, 'items': [dict(r) for r in rows[:50]], 'next': rows[49]['id'] if len(rows)>50 else None}


@router.get('/{diver}/{track}/episodes')
def episodes(diver: int, track: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    owner(request, db, diver); row=track_for(db, diver, track)
    cursor=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.id==after)) if after else None
    from sqlalchemy import tuple_
    continuation=tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id,TechniqueEpisode.id)>(cursor.start_at,cursor.start_id,cursor.id) if cursor else True
    rows=db.execute(select(TechniqueEpisode, Technique.label).outerjoin(Technique, Technique.id==TechniqueEpisode.technique_id).where(TechniqueEpisode.track_id==track, TechniqueEpisode.deleted.is_(False), continuation).order_by(TechniqueEpisode.start_at,TechniqueEpisode.start_id,TechniqueEpisode.id).limit(51)).all()
    return {'revision':row.revision,'items':[dict(snapshot(e),label=label) for e,label in rows[:50]],'next':rows[49][0].id if len(rows)>50 else None}


def snapshot(row):
    return {c.name: (getattr(row,c.name).isoformat() if isinstance(getattr(row,c.name),datetime) else getattr(row,c.name)) for c in row.__table__.columns}


class Change(ContextInput):
    revision: int
    label: str = Field(default='', max_length=120)
    technique_id: int | None = None
    scope: str = Field(max_length=10)
    start_at: datetime
    start_id: int = 0
    anchor_id: int | None = None
    uncertain_until: datetime | None = None
    gap: bool = False
    notes: str = Field(default='', max_length=2000)
    timezone: str = Field(default='UTC', max_length=80)
    precision: Literal['attempt','date','approximate'] = 'date'
    episode_id: int | None = None
    delete: bool = False


def plan(db, track, body):
    if body.scope != body.code and body.scope not in FAMILIES:
        raise HTTPException(422,'Unsupported family; choose an exact code')
    if body.start_at.tzinfo is not None:
        raise HTTPException(422,'Use a timezone-normalized naive UTC boundary')
    if body.uncertain_until and body.uncertain_until <= body.start_at:
        raise HTTPException(422,'Invalid approximate range')
    if body.anchor_id:
        anchor=db.scalar(select(Dive).where(Dive.id==body.anchor_id, Dive.diver_id==track.diver_id, Dive.dive_code==body.code, Dive.height==body.height, Dive.platform_type==body.apparatus))
        if anchor is None: raise HTTPException(404,'Anchor unavailable')
        body.start_at=anchor.history_occurred_at; body.start_id=anchor.id
    scope=[TechniqueEpisode.track_id==track.id, TechniqueEpisode.scope==body.scope, TechniqueEpisode.apparatus==body.apparatus, TechniqueEpisode.height==body.height, TechniqueEpisode.position.is_(None), TechniqueEpisode.sync.is_(None), TechniqueEpisode.deleted.is_(False)]
    if body.episode_id: scope.append(TechniqueEpisode.id!=body.episode_id)
    # Only immediate neighbors materialize; inserting preserves the upcoming change.
    key=(body.start_at,body.start_id)
    from sqlalchemy import tuple_
    boundary=tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id)
    previous=db.scalar(select(TechniqueEpisode).where(*scope,boundary<key).order_by(boundary.desc()).limit(1))
    upcoming=db.scalar(select(TechniqueEpisode).where(*scope,boundary>=key).order_by(boundary).limit(1))
    if upcoming and (upcoming.start_at,upcoming.start_id)==key and upcoming.id!=body.episode_id:
        raise HTTPException(409,'Boundary already exists')
    return previous,upcoming


@router.post('/{diver}/{track}/preview')
def preview(diver:int,track:int,body:Change,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver,True); row=track_for(db,diver,track,body.revision)
    previous,upcoming=plan(db,row,body)
    params=dict(body.model_dump(),diver=diver,track=track)
    counts=db.execute(text(RESOLVED+" SELECT count(*) affected,count(*) FILTER (WHERE source='recorded') explicit_preserved FROM resolved WHERE (history_occurred_at,id)>=(:start_at,:start_id)"),params).mappings().one()
    return {'counts':dict(counts),'revision':row.revision,'previous':snapshot(previous) if previous else None,'upcoming':snapshot(upcoming) if upcoming else None,'change':body.model_dump()}


@router.post('/{diver}/{track}/changes')
def change(diver:int,track:int,body:Change,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True); row=track_for(db,diver,track,body.revision)
    previous,upcoming=plan(db,row,body)
    editing = None
    if body.episode_id:
        editing=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.id==body.episode_id,TechniqueEpisode.track_id==track,TechniqueEpisode.deleted.is_(False)))
        if editing is None: raise HTTPException(404,'Episode unavailable')
        if (editing.scope,editing.apparatus,editing.height)!=(body.scope,body.apparatus,body.height):
            raise HTTPException(422,'Copy into another scope instead')
        from sqlalchemy import tuple_
        original_previous=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.scope==editing.scope,TechniqueEpisode.apparatus==editing.apparatus,TechniqueEpisode.height==editing.height,TechniqueEpisode.deleted.is_(False),tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id)<(editing.start_at,editing.start_id)).order_by(TechniqueEpisode.start_at.desc(),TechniqueEpisode.start_id.desc()).limit(1))
        if original_previous and (body.start_at,body.start_id)<=(original_previous.start_at,original_previous.start_id):raise HTTPException(409,'Edit crosses previous boundary')
        if previous and previous.id==editing.id: previous=None
        neighbor=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.scope==editing.scope,TechniqueEpisode.apparatus==editing.apparatus,TechniqueEpisode.height==editing.height,TechniqueEpisode.deleted.is_(False),TechniqueEpisode.start_at>editing.start_at).order_by(TechniqueEpisode.start_at,TechniqueEpisode.start_id).limit(1))
        if neighbor and (body.start_at,body.start_id)>=(neighbor.start_at,neighbor.start_id):
            raise HTTPException(409,'Edit crosses the next boundary')
    technique=None
    if not body.gap:
        if body.technique_id:
            technique=db.scalar(select(Technique).where(Technique.id==body.technique_id,Technique.track_id==track))
            if technique is None: raise HTTPException(404,'Technique unavailable')
        elif body.label.strip():
            technique=Technique(track_id=track,label=body.label.strip()); db.add(technique); db.flush()
        else: raise HTTPException(422,'Technique label required')
    before={'previous':snapshot(previous) if previous else None,'episode':snapshot(editing) if editing else None}
    if previous and (previous.end_at is None or (previous.end_at,previous.end_id)>(body.start_at,body.start_id)):
        previous.end_at,previous.end_id=body.start_at,body.start_id
    episode=TechniqueEpisode(track_id=track,technique_id=technique.id if technique else None,scope=body.scope,apparatus=body.apparatus,height=body.height,start_at=body.start_at,start_id=body.start_id,end_at=upcoming.start_at if upcoming else None,end_id=upcoming.start_id if upcoming else None,uncertain_until=body.uncertain_until,anchor_id=body.anchor_id,precision=body.precision,timezone=body.timezone,gap=body.gap,notes=body.notes)
    if editing:
        for key in ('technique_id','scope','apparatus','height','start_at','start_id','end_at','end_id','uncertain_until','anchor_id','precision','timezone','gap','notes'):
            setattr(editing,key,getattr(episode,key))
        episode=editing
    else: db.add(episode)
    db.flush(); row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='edit' if editing else 'create',before=before,after=snapshot(episode)))
    db.commit()
    return {'revision':row.revision,'episode':snapshot(episode)}


class Compare(ContextInput):
    left: int
    right: int
    modifiers: str = Field(max_length=200)
    mode: Literal['periods','recorded'] = 'periods'
    weighting: Literal['attempt','session'] = 'attempt'


@router.post('/{diver}/{track}/compare')
def compare(diver:int,track:int,body:Compare,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver); row=track_for(db,diver,track)
    pair=db.scalars(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.id.in_([body.left,body.right]),TechniqueEpisode.deleted.is_(False))).all()
    if len(pair)!=2: raise HTTPException(422,'Select two distinct episodes')
    for e in pair:
        if e.apparatus!=body.apparatus or e.height!=body.height or (e.position is not None and e.position!=body.position) or (e.sync is not None and e.sync!=body.sync):
            raise HTTPException(422,'Incompatible comparison context')
        from app.services.technique_history import family
        if e.scope not in (body.code,family(body.code)): raise HTTPException(422,'Incompatible exact code')
    by_id={e.id:e for e in pair}
    params=dict(body.model_dump(),diver=diver,track=track,left_identity=by_id[body.left].technique_id,right_identity=by_id[body.right].technique_id)
    sides=db.execute(text(comparison_sql(body.mode=='recorded',body.weighting=='session',params['left_identity']==params['right_identity'])),params).mappings().all()
    return {'revision':row.revision,'sides':[dict(s) for s in sides]}

class Bulk(ContextInput):
    revision: int
    ids: list[int] = Field(min_length=1,max_length=100)
    state: Literal['technique','mixed','unknown']
    technique_id: int | None = None


@router.post('/{diver}/{track}/assign')
def assign(diver:int,track:int,body:Bulk,request:Request,db:Session=Depends(get_db)):
    from app.models.technique_history import TechniqueAssignment
    user=owner(request,db,diver,True); row=track_for(db,diver,track,body.revision)
    if body.state=='technique':
        if not db.scalar(select(Technique.id).where(Technique.track_id==track,Technique.id==body.technique_id)):
            raise HTTPException(422,'Technique must belong to selected track')
    elif body.technique_id is not None: raise HTTPException(422,'Mixed/unknown cannot identify a technique')
    dives=db.scalars(select(Dive).where(Dive.id.in_(body.ids),Dive.diver_id==diver,Dive.dive_code==body.code,Dive.platform_type==body.apparatus,Dive.height==body.height,func.coalesce(Dive.position,'')==body.position,func.coalesce(Dive.is_sync,False)==body.sync).with_for_update()).all()
    if len(dives)!=len(set(body.ids)): raise HTTPException(403,'Selection contains unavailable context')
    existing={a.dive_id:a for a in db.scalars(select(TechniqueAssignment).where(TechniqueAssignment.track_id==track,TechniqueAssignment.dive_id.in_(body.ids)))}
    before=[snapshot(a) for a in existing.values()]
    for d in dives:
        a=existing.get(d.id)
        if a is None:
            a=TechniqueAssignment(track_id=track,dive_id=d.id);db.add(a)
        for k,v in dict(diver_id=diver,code=d.dive_code,apparatus=d.platform_type,height=d.height,position=d.position,sync=d.is_sync,state=body.state,technique_id=body.technique_id,episode_id=None).items(): setattr(a,k,v)
    row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='assign',before={'assignments':before},after={'ids':body.ids,'state':body.state,'technique_id':body.technique_id}))
    db.commit();return {'revision':row.revision,'count':len(dives)}


class RevisionInput(BaseModel):
    revision:int


@router.post('/{diver}/{track}/episodes/{episode}/delete')
def delete_episode(diver:int,track:int,episode:int,body:RevisionInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    e=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.id==episode,TechniqueEpisode.track_id==track,TechniqueEpisode.deleted.is_(False)))
    if e is None:raise HTTPException(404,'Episode unavailable')
    before=snapshot(e);e.deleted=True;row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='delete',before=before,after=snapshot(e)))
    db.commit();return {'revision':row.revision}


@router.post('/{diver}/{track}/undo')
def undo(diver:int,track:int,body:RevisionInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    rev=db.scalar(select(TechniqueRevision).where(TechniqueRevision.track_id==track,TechniqueRevision.revision==row.revision))
    if rev is None or rev.operation not in ('create','delete','edit'):raise HTTPException(422,'Latest operation cannot be undone')
    if rev.operation=='edit':
        old=rev.before['episode'];e=db.get(TechniqueEpisode,old['id'])
        for key,value in old.items():
            if key in ('start_at','end_at','uncertain_until') and value is not None:value=datetime.fromisoformat(value)
            setattr(e,key,value)
        previous=rev.before.get('previous')
        if previous:
            p=db.get(TechniqueEpisode,previous['id']);p.end_at=datetime.fromisoformat(previous['end_at']) if previous['end_at'] else None;p.end_id=previous['end_id']
    elif rev.operation=='delete':
        e=db.get(TechniqueEpisode,rev.before['id']);e.deleted=False
    else:
        e=db.get(TechniqueEpisode,rev.after['id']);e.deleted=True
        previous=rev.before.get('previous')
        if previous:
            p=db.get(TechniqueEpisode,previous['id']);p.end_at=datetime.fromisoformat(previous['end_at']) if previous['end_at'] else None;p.end_id=previous['end_id']
    row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='undo',before=rev.after,after=rev.before))
    db.commit();return {'revision':row.revision}

class Inventory(ContextInput):
    left:int
    right:int
    after:str = Field(default='',max_length=200)


@router.post('/{diver}/{track}/modifier-sets')
def modifier_sets(diver:int,track:int,body:Inventory,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver);row=track_for(db,diver,track)
    params=dict(body.model_dump(),diver=diver,track=track)
    rows=db.execute(text(RESOLVED+''' SELECT modifiers,
    count(*) FILTER(WHERE episode_id=:left) left_eligible,
    count(rating) FILTER(WHERE episode_id=:left) left_scored,
    count(*) FILTER(WHERE episode_id=:right) right_eligible,
    count(rating) FILTER(WHERE episode_id=:right) right_scored
    FROM resolved WHERE episode_id IN (:left,:right) AND NOT uncertain
    AND (:after='' OR modifiers>:after) GROUP BY modifiers ORDER BY modifiers LIMIT 51'''),params).mappings().all()
    return {'revision':row.revision,'items':[dict(r) for r in rows[:50]],'next':rows[49]['modifiers'] if len(rows)>50 else None}

class SessionFlag(ContextInput):
    revision:int
    session_id:int
    state:Literal['mixed','unknown']


@router.post('/{diver}/{track}/session-state')
def session_state(diver:int,track:int,body:SessionFlag,request:Request,db:Session=Depends(get_db)):
    from app.models.technique_history import TechniqueSessionState
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    exists=db.scalar(select(Dive.id).where(Dive.diver_id==diver,Dive.session_id==body.session_id,Dive.dive_code==body.code,Dive.platform_type==body.apparatus,Dive.height==body.height,func.coalesce(Dive.position,'')==body.position,func.coalesce(Dive.is_sync,False)==body.sync).limit(1))
    if exists is None:raise HTTPException(404,'Session context unavailable')
    values=dict(track_id=track,session_id=body.session_id,code=body.code,apparatus=body.apparatus,height=body.height,position=body.position,sync=body.sync)
    state=db.scalar(select(TechniqueSessionState).filter_by(**values))
    before=snapshot(state) if state else {}
    if state is None:state=TechniqueSessionState(**values);db.add(state)
    state.state=body.state;db.flush();row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='session',before=before,after=snapshot(state)))
    db.commit();return {'revision':row.revision}


class CopyTarget(BaseModel):
    scope:str=Field(min_length=1,max_length=10)
    apparatus:str=Field(min_length=1,max_length=20)
    height:str=Field(min_length=1,max_length=5)


class CopyInput(BaseModel):
    revision:int
    episode_id:int
    targets:list[CopyTarget]=Field(min_length=1,max_length=16)
    commit:bool=False


@router.post('/{diver}/{track}/copy')
def copy_once(diver:int,track:int,body:CopyInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    source=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.id==body.episode_id,TechniqueEpisode.track_id==track,TechniqueEpisode.deleted.is_(False)))
    if source is None:raise HTTPException(404,'Source unavailable')
    if len({(t.scope,t.apparatus,t.height) for t in body.targets})!=len(body.targets):raise HTTPException(422,'Duplicate targets')
    plans=[]
    for target in body.targets:
        # Exact codes come from the existing catalog rather than guessed armstand groups.
        from app.models.dive_code import DiveCode
        if target.scope not in FAMILIES and not db.scalar(select(DiveCode.dive_code).where(DiveCode.dive_code==target.scope).limit(1)):
            raise HTTPException(422,'Unknown exact code')
        c=Change(code=target.scope,scope=target.scope,apparatus=target.apparatus,height=target.height,revision=body.revision,start_at=source.start_at,start_id=source.start_id)
        previous,upcoming=plan(db,row,c)
        plans.append((target,previous,upcoming))
    preview=[{'scope':t.model_dump(),'previous':snapshot(p) if p else None,'upcoming':snapshot(n) if n else None} for t,p,n in plans]
    if not body.commit:return {'revision':row.revision,'targets':preview}
    ids=[]
    for target,previous,upcoming in plans:
        if previous and (previous.end_at is None or (previous.end_at,previous.end_id)>(source.start_at,source.start_id)):
            previous.end_at,previous.end_id=source.start_at,source.start_id
        values={k:v for k,v in snapshot(source).items() if k not in ('id','start_at','end_at','uncertain_until','source_episode_id','anchor_id')}
        values.update(scope=target.scope,apparatus=target.apparatus,height=target.height,start_at=source.start_at,end_at=upcoming.start_at if upcoming else source.end_at,end_id=upcoming.start_id if upcoming else source.end_id,uncertain_until=source.uncertain_until,source_episode_id=source.id)
        copied=TechniqueEpisode(**values);db.add(copied);db.flush();ids.append(copied.id)
    row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='copy',before={'targets':preview},after={'ids':ids,'source':source.id}))
    db.commit();return {'revision':row.revision,'ids':ids}

class ChartInput(ContextInput):
    episode:int
    after:int=0


@router.post('/{diver}/{track}/chart')
def chart(diver:int,track:int,body:ChartInput,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver);row=track_for(db,diver,track)
    params=dict(body.model_dump(),diver=diver,track=track)
    rows=db.execute(text(RESOLVED+''' SELECT session_id,min(history_occurred_at) occurred_at,
    percentile_cont(0.5) WITHIN GROUP(ORDER BY rating) median,
    percentile_cont(0.25) WITHIN GROUP(ORDER BY rating) q1,
    percentile_cont(0.75) WITHIN GROUP(ORDER BY rating) q3,count(rating) scored,count(*) eligible
    FROM resolved WHERE episode_id=:episode AND NOT uncertain AND session_id>:after
    GROUP BY session_id ORDER BY session_id LIMIT 51'''),params).mappings().all()
    return {'revision':row.revision,'items':[dict(r) for r in rows[:50]],'next':rows[49]['session_id'] if len(rows)>50 else None}

class RenameInput(RevisionInput):
    label:str=Field(min_length=1,max_length=120)


@router.post('/{diver}/{track}/techniques/{technique}/rename')
def rename(diver:int,track:int,technique:int,body:RenameInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    identity=db.scalar(select(Technique).where(Technique.id==technique,Technique.track_id==track))
    if identity is None:raise HTTPException(404,'Technique unavailable')
    before=snapshot(identity);identity.label=body.label;row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='rename',before=before,after=snapshot(identity)))
    db.commit();return {'revision':row.revision}

class EndInput(RevisionInput):
    episode_id:int
    end_at:datetime
    end_id:int=0
    commit:bool=False


@router.post('/{diver}/{track}/end')
def end_episode(diver:int,track:int,body:EndInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    episode=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.id==body.episode_id,TechniqueEpisode.track_id==track,TechniqueEpisode.deleted.is_(False)))
    if episode is None:raise HTTPException(404,'Episode unavailable')
    if body.end_at.tzinfo or (body.end_at,body.end_id)<=(episode.start_at,episode.start_id):raise HTTPException(422,'Invalid end boundary')
    if episode.end_at and (body.end_at,body.end_id)>(episode.end_at,episode.end_id):raise HTTPException(409,'Cannot cross upcoming boundary')
    preview={'before':snapshot(episode),'end_at':body.end_at,'end_id':body.end_id,'family_fallback':True}
    if not body.commit:return {'revision':row.revision,'preview':preview}
    before={'episode':snapshot(episode),'previous':None};episode.end_at,episode.end_id=body.end_at,body.end_id;row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='edit',before=before,after=snapshot(episode)))
    db.commit();return {'revision':row.revision}
