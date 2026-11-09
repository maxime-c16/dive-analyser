"""Owner-only, revision fenced technique history. All handlers run in threadpool."""
from datetime import datetime
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func
from sqlalchemy.orm import Session, load_only
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
    else:
        stmt = stmt.with_for_update(read=True)
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
    rows = db.execute(text(RESOLVED + ' SELECT id,session_id,video_uuid,dive_code,dive_datetime,history_occurred_at,performance,late_import,episode_id,recorded_episode_id,recorded_episode_deleted,intended_id,state,use_id,(SELECT label FROM techniques WHERE techniques.id=resolved.use_id AND techniques.track_id=:track) use_label,source FROM resolved WHERE (CAST(:session_id AS integer) IS NULL OR session_id=:session_id) AND (CAST(:from_date AS timestamp) IS NULL OR history_occurred_at>=:from_date) AND (CAST(:to_date AS timestamp) IS NULL OR history_occurred_at<:to_date) AND (:after=0 OR (history_occurred_at,id)>(SELECT history_occurred_at,id FROM eligible WHERE id=:after)) ORDER BY history_occurred_at,id LIMIT 51'), params).mappings().all()
    return {'revision': row.revision, 'items': [dict(r) for r in rows[:50]], 'next': rows[49]['id'] if len(rows)>50 else None}


@router.get('/{diver}/{track}/episodes')
def episodes(diver: int, track: int, request: Request, after: int = 0, db: Session = Depends(get_db)):
    owner(request, db, diver); row=track_for(db, diver, track)
    cursor=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.id==after)) if after else None
    from sqlalchemy import tuple_
    continuation=tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id,TechniqueEpisode.id)>(cursor.start_at,cursor.start_id,cursor.id) if cursor else True
    rows=db.execute(select(TechniqueEpisode, Technique.label, Dive.id.label('available_anchor')).outerjoin(Technique, Technique.id==TechniqueEpisode.technique_id).outerjoin(Dive,(Dive.id==TechniqueEpisode.anchor_id)&(Dive.diver_id==diver)).where(TechniqueEpisode.track_id==track, TechniqueEpisode.deleted.is_(False), continuation).order_by(TechniqueEpisode.start_at,TechniqueEpisode.start_id,TechniqueEpisode.id).limit(51)).all()
    return {'revision':row.revision,'items':[dict(snapshot(e),label=label,anchor_unavailable=e.precision=='attempt' and available is None) for e,label,available in rows[:50]],'next':rows[49][0].id if len(rows)>50 else None}


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
    normalized:bool=False
    constrain_position:bool=False
    constrain_sync:bool=False
    episode_id: int | None = None
    delete: bool = False


def plan(db, track, body):
    if body.scope != body.code and body.scope not in FAMILIES:
        raise HTTPException(422,'Unsupported family; choose an exact code')
    if not body.normalized and not body.anchor_id:
        from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
        from datetime import timezone
        try:zone=ZoneInfo(body.timezone)
        except ZoneInfoNotFoundError:raise HTTPException(422,'Unknown timezone')
        def normalize(value):
            if value is None:return None
            if value.tzinfo is not None:return value.astimezone(timezone.utc).replace(tzinfo=None)
            local=value.replace(tzinfo=zone)
            if local.astimezone(timezone.utc).astimezone(zone).replace(tzinfo=None)!=value:raise HTTPException(422,'Nonexistent local time')
            return local.astimezone(timezone.utc).replace(tzinfo=None)
        body.start_at=normalize(body.start_at);body.uncertain_until=normalize(body.uncertain_until);body.normalized=True
    if body.start_at.tzinfo is not None:
        raise HTTPException(422,'Use a timezone-normalized naive UTC boundary')
    if body.uncertain_until and body.uncertain_until <= body.start_at:
        raise HTTPException(422,'Invalid approximate range')
    if body.anchor_id:
        anchor=db.scalar(select(Dive).options(load_only(Dive.id,Dive.history_occurred_at)).where(Dive.id==body.anchor_id, Dive.diver_id==track.diver_id, Dive.dive_code==body.code, Dive.height==body.height, Dive.platform_type==body.apparatus))
        if anchor is None: raise HTTPException(404,'Anchor unavailable')
        body.start_at=anchor.history_occurred_at; body.start_id=anchor.id;body.normalized=True
    scope=[TechniqueEpisode.track_id==track.id, TechniqueEpisode.scope==body.scope, TechniqueEpisode.apparatus==body.apparatus, TechniqueEpisode.height==body.height, (TechniqueEpisode.position==body.position if body.constrain_position else TechniqueEpisode.position.is_(None)), (TechniqueEpisode.sync==body.sync if body.constrain_sync else TechniqueEpisode.sync.is_(None)), TechniqueEpisode.deleted.is_(False)]
    if body.episode_id: scope.append(TechniqueEpisode.id!=body.episode_id)
    # Only immediate neighbors materialize; inserting preserves the upcoming change.
    key=(body.start_at,body.start_id)
    from sqlalchemy import tuple_
    boundary=tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id)
    previous=db.scalar(select(TechniqueEpisode).where(*scope,boundary<key).order_by(boundary.desc()).limit(1))
    upcoming=db.scalar(select(TechniqueEpisode).where(*scope,boundary>=key).order_by(boundary).limit(1))
    if upcoming and (upcoming.start_at,upcoming.start_id)==key and upcoming.id!=body.episode_id:
        raise HTTPException(409,'Boundary already exists')
    if body.constrain_position != body.constrain_sync:
        peer_scope=[TechniqueEpisode.track_id==track.id,TechniqueEpisode.scope==body.scope,TechniqueEpisode.apparatus==body.apparatus,TechniqueEpisode.height==body.height,TechniqueEpisode.deleted.is_(False)]
        if body.constrain_position:peer_scope.extend([TechniqueEpisode.position.is_(None),TechniqueEpisode.sync.is_not(None)])
        else:peer_scope.extend([TechniqueEpisode.position.is_not(None),TechniqueEpisode.sync.is_(None)])
        from sqlalchemy import or_
        peer_scope.append(or_(TechniqueEpisode.end_at.is_(None),tuple_(TechniqueEpisode.end_at,TechniqueEpisode.end_id)>key))
        if upcoming:peer_scope.append(tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id)<(upcoming.start_at,upcoming.start_id))
        if db.scalar(select(TechniqueEpisode.id).where(*peer_scope).limit(1)):raise HTTPException(409,'Ambiguous equally specific context overlap')
    return previous,upcoming


def preview_counts(db,row,body,upcoming,stop_override=None):
    stop=stop_override or ((upcoming.start_at,upcoming.start_id) if upcoming else (None,None))
    params=dict(body.model_dump(),diver=row.diver_id,track=row.id,stop_at=stop[0],stop_id=stop[1])
    sql=RESOLVED
    if body.scope in FAMILIES:sql=sql.replace('d.dive_code=:code',"d.dive_code LIKE :scope || '%'")
    if not body.constrain_position:sql=sql.replace("coalesce(d.position,'')=:position",'true')
    if not body.constrain_sync:sql=sql.replace('coalesce(d.is_sync,false)=:sync','true')
    family_guard=' AND (intended_scope IS NULL OR intended_scope<>dive_code)' if body.scope in FAMILIES else ''
    counts=db.execute(text(sql+" SELECT count(*) affected,count(*) FILTER (WHERE source='recorded') explicit_preserved FROM resolved WHERE (history_occurred_at,id)>=(:start_at,:start_id) AND (CAST(:stop_at AS timestamp) IS NULL OR (history_occurred_at,id)<(:stop_at,:stop_id))"+family_guard),params).mappings().one()
    return dict(counts)


@router.post('/{diver}/{track}/preview')
def preview(diver:int,track:int,body:Change,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver,True); row=track_for(db,diver,track,body.revision)
    previous,upcoming=plan(db,row,body)
    original=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.id==body.episode_id)) if body.episode_id else None
    if body.episode_id and original is None:raise HTTPException(404,'Episode unavailable')
    counts=preview_counts(db,row,body,upcoming)
    return {'original':snapshot(original) if original else None,'counts':dict(counts),'revision':row.revision,'previous':snapshot(previous) if previous else None,'upcoming':snapshot(upcoming) if upcoming else None,'change':body.model_dump()}


@router.post('/{diver}/{track}/changes')
def change(diver:int,track:int,body:Change,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True); row=track_for(db,diver,track,body.revision)
    previous,upcoming=plan(db,row,body)
    editing = None
    if body.episode_id:
        editing=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.id==body.episode_id,TechniqueEpisode.track_id==track,TechniqueEpisode.deleted.is_(False)))
        if editing is None: raise HTTPException(404,'Episode unavailable')
        same_scope=(editing.scope,editing.apparatus,editing.height,editing.position,editing.sync)==(body.scope,body.apparatus,body.height,body.position if body.constrain_position else None,body.sync if body.constrain_sync else None)
        if same_scope:
            from sqlalchemy import tuple_
            original_previous=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.scope==editing.scope,TechniqueEpisode.apparatus==editing.apparatus,TechniqueEpisode.height==editing.height,TechniqueEpisode.position.is_not_distinct_from(editing.position),TechniqueEpisode.sync.is_not_distinct_from(editing.sync),TechniqueEpisode.deleted.is_(False),tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id)<(editing.start_at,editing.start_id)).order_by(TechniqueEpisode.start_at.desc(),TechniqueEpisode.start_id.desc()).limit(1))
            if original_previous and (body.start_at,body.start_id)<=(original_previous.start_at,original_previous.start_id):raise HTTPException(409,'Edit crosses previous boundary')
            if previous and previous.id==editing.id: previous=None
            neighbor=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.scope==editing.scope,TechniqueEpisode.apparatus==editing.apparatus,TechniqueEpisode.height==editing.height,TechniqueEpisode.position.is_not_distinct_from(editing.position),TechniqueEpisode.sync.is_not_distinct_from(editing.sync),TechniqueEpisode.deleted.is_(False),tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id)>(editing.start_at,editing.start_id)).order_by(TechniqueEpisode.start_at,TechniqueEpisode.start_id).limit(1))
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
    if previous and (previous.end_at is None or (previous.end_at,previous.end_id)>(body.start_at,body.start_id) or (editing and same_scope and (previous.end_at,previous.end_id)==(editing.start_at,editing.start_id))):
        previous.end_at,previous.end_id=body.start_at,body.start_id
    episode=TechniqueEpisode(track_id=track,technique_id=technique.id if technique else None,scope=body.scope,apparatus=body.apparatus,height=body.height,position=body.position if body.constrain_position else None,sync=body.sync if body.constrain_sync else None,start_at=body.start_at,start_id=body.start_id,end_at=upcoming.start_at if upcoming else None,end_id=upcoming.start_id if upcoming else None,uncertain_until=body.uncertain_until,anchor_id=body.anchor_id,precision=body.precision,timezone=body.timezone,gap=body.gap,notes=body.notes)
    if editing:
        for key in ('technique_id','scope','apparatus','height','position','sync','start_at','start_id','end_at','end_id','uncertain_until','anchor_id','precision','timezone','gap','notes'):
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
    labels=dict(db.execute(select(Technique.id,Technique.label).where(Technique.track_id==track,Technique.id.in_([e.technique_id for e in pair]))).all())
    excluded=db.execute(text(RESOLVED+" SELECT count(*) FILTER(WHERE uncertain) uncertain,count(*) FILTER(WHERE NOT uncertain AND modifiers<>:modifiers) other_modifiers,count(*) FILTER(WHERE NOT uncertain AND modifiers=:modifiers AND (source<>'recorded' OR state<>'technique')) not_recorded,count(*) FILTER(WHERE NOT uncertain AND modifiers=:modifiers AND source='recorded' AND state='technique' AND use_id IN (:left_identity,:right_identity)) recorded_eligible,count(*) FILTER(WHERE NOT uncertain AND modifiers=:modifiers AND source='recorded' AND state='technique' AND use_id NOT IN (:left_identity,:right_identity)) other_techniques FROM resolved WHERE episode_id IN (:left,:right)"),params).mappings().one()
    excluded=dict(excluded)
    recorded_eligible=excluded.pop('recorded_eligible')
    if body.mode=='periods':excluded['not_recorded']=0;excluded['other_techniques']=0
    from sqlalchemy import or_,and_
    from app.services.technique_history import family
    overlaps=[]
    for e in pair:
        interval=[or_(TechniqueEpisode.end_at.is_(None),TechniqueEpisode.end_at>=e.start_at)]
        if e.end_at:interval.append(TechniqueEpisode.start_at<=e.end_at)
        overlaps.append(and_(*interval))
    others=db.execute(select(TechniqueEpisode.id,TechniqueTrack.id.label('track_id'),TechniqueTrack.name).join(TechniqueTrack,TechniqueTrack.id==TechniqueEpisode.track_id).where(TechniqueTrack.diver_id==diver,TechniqueTrack.id!=track,TechniqueEpisode.deleted.is_(False),TechniqueEpisode.scope.in_([body.code,family(body.code)]),TechniqueEpisode.apparatus==body.apparatus,TechniqueEpisode.height==body.height,or_(TechniqueEpisode.position.is_(None),TechniqueEpisode.position==body.position),or_(TechniqueEpisode.sync.is_(None),TechniqueEpisode.sync==body.sync),or_(*overlaps)).order_by(TechniqueEpisode.id).limit(51)).mappings().all()
    same=params['left_identity']==params['right_identity']
    return {'revision':row.revision,'kind':'recorded-by-episode' if body.mode=='recorded' and same else body.mode,'excluded':excluded,'recorded_eligible':recorded_eligible,'other_tracks':[dict(o) for o in others[:50]],'more_other_tracks':len(others)>50,'sides':[dict(s,label=labels.get(by_id[body.left if s['side']==0 else body.right].technique_id)) for s in sides]}

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
    dives=db.scalars(select(Dive).options(load_only(Dive.id,Dive.diver_id,Dive.dive_code,Dive.platform_type,Dive.height,Dive.position,Dive.is_sync)).where(Dive.id.in_(body.ids),Dive.diver_id==diver,Dive.dive_code==body.code,Dive.platform_type==body.apparatus,Dive.height==body.height,func.coalesce(Dive.position,'')==body.position,func.coalesce(Dive.is_sync,False)==body.sync).with_for_update()).all()
    if len(dives)!=len(set(body.ids)): raise HTTPException(403,'Selection contains unavailable context')
    existing={a.dive_id:a for a in db.scalars(select(TechniqueAssignment).where(TechniqueAssignment.track_id==track,TechniqueAssignment.dive_id.in_(body.ids)))}
    from sqlalchemy import bindparam
    provenance_sql=text(RESOLVED+' SELECT id,episode_id FROM resolved WHERE id IN :selected_ids').bindparams(bindparam('selected_ids',expanding=True))
    provenance=dict(db.execute(provenance_sql,dict(body.model_dump(),diver=diver,track=track,selected_ids=body.ids)).all())
    before=[snapshot(a) for a in existing.values()]
    for d in dives:
        a=existing.get(d.id)
        if a is None:
            a=TechniqueAssignment(track_id=track,dive_id=d.id);db.add(a)
        for k,v in dict(diver_id=diver,code=d.dive_code,apparatus=d.platform_type,height=d.height,position=d.position,sync=d.is_sync,state=body.state,technique_id=body.technique_id,episode_id=provenance.get(d.id)).items(): setattr(a,k,v)
    row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='assign',before={'assignments':before},after={'ids':body.ids,'state':body.state,'technique_id':body.technique_id}))
    db.commit();return {'revision':row.revision,'count':len(dives)}


class RevisionInput(BaseModel):
    revision:int


class DeleteInput(RevisionInput):
    commit:bool=False


@router.post('/{diver}/{track}/episodes/{episode}/delete')
def delete_episode(diver:int,track:int,episode:int,body:DeleteInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    e=db.scalar(select(TechniqueEpisode).where(TechniqueEpisode.id==episode,TechniqueEpisode.track_id==track,TechniqueEpisode.deleted.is_(False)))
    if e is None:raise HTTPException(404,'Episode unavailable')
    if not body.commit:
        sql=RESOLVED.replace('d.dive_code=:code','true').replace("coalesce(d.position,'')=:position",'true').replace('coalesce(d.is_sync,false)=:sync','true')
        counts=db.execute(text(sql+" SELECT count(*) eligible,count(*) FILTER(WHERE source='recorded') explicit_preserved FROM resolved WHERE episode_id=:episode"),{'diver':diver,'track':track,'apparatus':e.apparatus,'height':e.height,'episode':e.id}).mappings().one()
        return {'revision':row.revision,'preview':dict(counts),'family_fallback':True}
    before=snapshot(e);e.deleted=True;row.revision+=1
    db.add(TechniqueRevision(track_id=track,revision=row.revision,author_id=user.id,operation='delete',before=before,after=snapshot(e)))
    db.commit();return {'revision':row.revision}


@router.post('/{diver}/{track}/undo')
def undo(diver:int,track:int,body:RevisionInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    rev=db.scalar(select(TechniqueRevision).where(TechniqueRevision.track_id==track,TechniqueRevision.revision==row.revision))
    if rev is None or rev.operation not in ('create','delete','edit','copy','rename'):raise HTTPException(422,'Latest operation cannot be undone')
    if rev.operation=='copy':
        copies=db.scalars(select(TechniqueEpisode).where(TechniqueEpisode.track_id==track,TechniqueEpisode.id.in_(rev.after['ids']))).all()
        for copied in copies:copied.deleted=True
        for target in rev.before['targets']:
            previous=target.get('previous')
            if previous:
                p=db.get(TechniqueEpisode,previous['id']);p.end_at=datetime.fromisoformat(previous['end_at']) if previous['end_at'] else None;p.end_id=previous['end_id']
    elif rev.operation=='rename':
        identity=db.scalar(select(Technique).where(Technique.id==rev.before['id'],Technique.track_id==track))
        identity.label=rev.before['label']
    elif rev.operation=='edit':
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
        c=Change(code=target.scope,scope=target.scope,apparatus=target.apparatus,height=target.height,revision=body.revision,start_at=source.start_at,start_id=source.start_id,normalized=True,constrain_position=source.position is not None,constrain_sync=source.sync is not None,position=source.position or '',sync=bool(source.sync))
        previous,upcoming=plan(db,row,c)
        plans.append((target,previous,upcoming,c))
    preview=[]
    for t,p,n,c in plans:
        ends=[key for key in [(source.end_at,source.end_id),(n.start_at,n.start_id) if n else (None,None)] if key[0] is not None]
        preview.append({'scope':t.model_dump(),'previous':snapshot(p) if p else None,'upcoming':snapshot(n) if n else None,'counts':preview_counts(db,row,c,n,min(ends) if ends else None)})
    if not body.commit:return {'revision':row.revision,'targets':preview}
    ids=[]
    for target,previous,upcoming,c in plans:
        if previous and (previous.end_at is None or (previous.end_at,previous.end_id)>(source.start_at,source.start_id)):
            previous.end_at,previous.end_id=source.start_at,source.start_id
        values={k:v for k,v in snapshot(source).items() if k not in ('id','created_at','start_at','end_at','uncertain_until','source_episode_id','anchor_id')}
        values.update(scope=target.scope,apparatus=target.apparatus,height=target.height,start_at=source.start_at,end_at=upcoming.start_at if upcoming else source.end_at,end_id=upcoming.start_id if upcoming else source.end_id,uncertain_until=source.uncertain_until,source_episode_id=source.id)
        ends=[key for key in [(source.end_at,source.end_id),(upcoming.start_at,upcoming.start_id) if upcoming else (None,None)] if key[0] is not None]
        if ends:values['end_at'],values['end_id']=min(ends)
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
    rows=db.execute(text(RESOLVED+''', bins AS ( SELECT session_id,min(history_occurred_at) occurred_at,
    percentile_cont(0.5) WITHIN GROUP(ORDER BY rating) median,
    CASE WHEN count(rating)>=2 THEN percentile_cont(0.25) WITHIN GROUP(ORDER BY rating) END q1,
    CASE WHEN count(rating)>=2 THEN percentile_cont(0.75) WITHIN GROUP(ORDER BY rating) END q3,count(rating) scored,count(*) eligible
    FROM resolved WHERE episode_id=:episode AND NOT uncertain
    GROUP BY session_id HAVING count(rating)>0), page AS (SELECT * FROM bins WHERE (:after=0 OR (occurred_at,session_id)>(SELECT occurred_at,session_id FROM bins WHERE session_id=:after)) ORDER BY occurred_at,session_id LIMIT 51)
    SELECT page.*,curves.curve_median,curves.curve_q1,curves.curve_q3 FROM page LEFT JOIN LATERAL (
    SELECT percentile_cont(0.5) WITHIN GROUP(ORDER BY median) FILTER(WHERE rn<=3) curve_median,
    percentile_cont(0.25) WITHIN GROUP(ORDER BY median) curve_q1,
    percentile_cont(0.75) WITHIN GROUP(ORDER BY median) curve_q3 FROM (
    SELECT median,row_number() OVER(ORDER BY occurred_at DESC,session_id DESC) rn FROM bins b
    WHERE (b.occurred_at,b.session_id)<=(page.occurred_at,page.session_id)
    ORDER BY occurred_at DESC,session_id DESC LIMIT 5) preceding
    ) curves ON true ORDER BY page.occurred_at,page.session_id'''),params).mappings().all()
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

@router.get('/{diver}/{track}/revisions')
def revisions(diver:int,track:int,request:Request,after:int=0,db:Session=Depends(get_db)):
    owner(request,db,diver);row=track_for(db,diver,track)
    # Audit payloads may contain 100 assignment snapshots; paginate metadata only.
    rows=db.execute(select(TechniqueRevision.revision,TechniqueRevision.author_id,TechniqueRevision.operation,TechniqueRevision.created_at).where(TechniqueRevision.track_id==track,TechniqueRevision.revision>after).order_by(TechniqueRevision.revision).limit(51)).mappings().all()
    return {'revision':row.revision,'items':[dict(r) for r in rows[:50]],'next':rows[49]['revision'] if len(rows)>50 else None}

class CorrectionInput(RevisionInput):
    track_revisions:dict[int,int]=Field(default_factory=dict,max_length=16)
    attempt_id:int
    occurred_at:datetime
    commit:bool=False


@router.post('/{diver}/{track}/correct-order')
def correct_order(diver:int,track:int,body:CorrectionInput,request:Request,db:Session=Depends(get_db)):
    user=owner(request,db,diver,True);row=track_for(db,diver,track,body.revision)
    if body.occurred_at.tzinfo:raise HTTPException(422,'Expected UTC without offset')
    # A correction affects every track. Bound fan-out before materializing/writing.
    all_tracks=db.scalars(select(TechniqueTrack).where(TechniqueTrack.diver_id==diver).order_by(TechniqueTrack.id).limit(17).with_for_update()).all()
    if len(all_tracks)>16:raise HTTPException(422,'Correction exceeds 16-track transaction budget')
    track_revisions={t.id:t.revision for t in all_tracks}
    if body.commit and body.track_revisions!=track_revisions:raise HTTPException(409,'Refresh correction preview')
    dive=db.scalar(select(Dive).options(load_only(Dive.id,Dive.history_occurred_at)).where(Dive.id==body.attempt_id,Dive.diver_id==diver).with_for_update())
    if dive is None:raise HTTPException(404,'Attempt unavailable')
    # Keep boundary keys intact: correction is explicitly an attempt-order action.
    # Anchored boundary movement is a separate previewed episode edit.
    low,high=sorted([dive.history_occurred_at,body.occurred_at])
    affected=db.scalar(select(func.count()).select_from(Dive).where(Dive.diver_id==diver,Dive.history_occurred_at>=low,Dive.history_occurred_at<=high))
    preview={'attempt_id':dive.id,'before':dive.history_occurred_at.isoformat(),'after':body.occurred_at.isoformat(),'affected_attempts':affected,'anchor_boundaries_preserved':True,'track_revisions':track_revisions}
    if not body.commit:return {'revision':row.revision,'preview':preview}
    db.execute(text("SELECT set_config('app.history_correction','on',true)"))
    db.execute(text('UPDATE dives SET history_occurred_at=:occurred WHERE id=:id AND diver_id=:diver'),{'occurred':body.occurred_at,'id':dive.id,'diver':diver})
    db.execute(text("SELECT set_config('app.history_correction','off',true)"))
    for t in all_tracks:
        t.revision+=1
        db.add(TechniqueRevision(track_id=t.id,revision=t.revision,author_id=user.id,operation='order-correction',before={'key':preview['before']},after=preview))
    db.commit();return {'revision':row.revision,'preview':preview}

class PreferenceInput(BaseModel):
    timezone:str=Field(min_length=1,max_length=80)


@router.get('/preferences')
def preferences(request:Request,db:Session=Depends(get_db)):
    from app.models.technique_history import TechniquePreference
    user=optional_session_user(request,db)
    if user is None:raise HTTPException(401,'Authentication required')
    preference=db.get(TechniquePreference,user.id)
    return {'timezone':preference.timezone if preference else 'UTC'}


@router.post('/preferences')
def save_preferences(body:PreferenceInput,request:Request,db:Session=Depends(get_db)):
    from zoneinfo import ZoneInfo,ZoneInfoNotFoundError
    from app.models.technique_history import TechniquePreference
    user=optional_session_user(request,db)
    if user is None:raise HTTPException(401,'Authentication required')
    try:ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:raise HTTPException(422,'Unknown timezone')
    # Serialize preference upserts on the existing user row.
    from app.models.user_auth import AppUser
    db.execute(select(AppUser.id).where(AppUser.id==user.id).with_for_update())
    preference=db.get(TechniquePreference,user.id)
    if preference is None:preference=TechniquePreference(user_id=user.id,timezone=body.timezone);db.add(preference)
    else:preference.timezone=body.timezone
    db.commit();return {'timezone':body.timezone}

@router.get('/{diver}/{track}/revisions/{revision}')
def revision_detail(diver:int,track:int,revision:int,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver);track_for(db,diver,track)
    record=db.scalar(select(TechniqueRevision).where(TechniqueRevision.track_id==track,TechniqueRevision.revision==revision))
    if record is None:raise HTTPException(404,'Revision unavailable')
    return snapshot(record)

class TrackChartInput(ContextInput):
    after:str=Field(default='',max_length=256)


@router.post('/{diver}/{track}/track-chart')
def track_chart(diver:int,track:int,body:TrackChartInput,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver);row=track_for(db,diver,track)
    params=dict(body.model_dump(),diver=diver,track=track)
    sql=RESOLVED+''', bins AS (
    SELECT session_id,episode_id,use_id,state,source,uncertain,min(history_occurred_at) occurred_at,
    percentile_cont(0.5) WITHIN GROUP(ORDER BY rating) median,count(rating) scored,
    CASE WHEN count(rating)>=2 THEN percentile_cont(0.25) WITHIN GROUP(ORDER BY rating) END q1,
    CASE WHEN count(rating)>=2 THEN percentile_cont(0.75) WITHIN GROUP(ORDER BY rating) END q3,
    to_char(min(history_occurred_at),'YYYY-MM-DD"T"HH24:MI:SS.US')||':'||lpad(session_id::text,10,'0')||':'||lpad(coalesce(episode_id,0)::text,10,'0')||':'||lpad(coalesce(use_id,0)::text,10,'0')||':'||state||':'||source point_key
    FROM resolved GROUP BY session_id,episode_id,use_id,state,source,uncertain HAVING count(rating)>0
    ), boundaries AS (
    SELECT *,CASE WHEN episode_id IS DISTINCT FROM lag(episode_id) OVER(ORDER BY point_key)
    OR uncertain IS DISTINCT FROM lag(uncertain) OVER(ORDER BY point_key)
    OR (state IN ('mixed','unknown','unrecorded')) IS DISTINCT FROM lag(state IN ('mixed','unknown','unrecorded')) OVER(ORDER BY point_key)
    THEN 1 ELSE 0 END change FROM bins
    ), segments AS (
    SELECT *,sum(change) OVER(ORDER BY point_key) segment FROM boundaries
    ), page AS (SELECT * FROM segments WHERE point_key>:after ORDER BY point_key LIMIT 51)
    SELECT page.*,curves.curve_median,curves.curve_q1,curves.curve_q3 FROM page LEFT JOIN LATERAL (
    SELECT CASE WHEN page.state='technique' AND NOT page.uncertain AND page.episode_id IS NOT NULL THEN percentile_cont(0.5) WITHIN GROUP(ORDER BY median) FILTER(WHERE rn<=3) END curve_median,
    CASE WHEN page.state='technique' AND NOT page.uncertain AND page.episode_id IS NOT NULL THEN percentile_cont(0.25) WITHIN GROUP(ORDER BY median) END curve_q1,
    CASE WHEN page.state='technique' AND NOT page.uncertain AND page.episode_id IS NOT NULL THEN percentile_cont(0.75) WITHIN GROUP(ORDER BY median) END curve_q3
    FROM (SELECT median,row_number() OVER(ORDER BY point_key DESC) rn FROM segments b WHERE b.segment=page.segment AND b.point_key<=page.point_key ORDER BY point_key DESC LIMIT 5) preceding
    ) curves ON true ORDER BY point_key'''
    rows=db.execute(text(sql),params).mappings().all()
    ids={r['episode_id'] for r in rows[:50] if r['episode_id'] is not None}
    boundaries=db.execute(select(TechniqueEpisode.id,TechniqueEpisode.start_at,TechniqueEpisode.end_at,TechniqueEpisode.uncertain_until,Technique.label).outerjoin(Technique,Technique.id==TechniqueEpisode.technique_id).where(TechniqueEpisode.track_id==track,TechniqueEpisode.id.in_(ids)).order_by(TechniqueEpisode.start_at,TechniqueEpisode.start_id)).mappings().all() if ids else []
    return {'revision':row.revision,'items':[dict(r) for r in rows[:50]],'boundaries':[dict(b) for b in boundaries],'next':rows[49]['point_key'] if len(rows)>50 else None}

@router.get('/contexts')
def context_inventory(request:Request,code:str=Query(min_length=1,max_length=10),after:str=Query(default='',max_length=256),db:Session=Depends(get_db)):
    import json
    from sqlalchemy import tuple_
    from app.models.user_auth import UserDiverAccess
    user=optional_session_user(request,db)
    if user is None:raise HTTPException(401,'Authentication required')
    columns=(Dive.diver_id,Dive.platform_type,Dive.height,func.coalesce(Dive.position,''),func.coalesce(Dive.is_sync,False))
    stmt=select(Dive.diver_id,Dive.platform_type.label('apparatus'),Dive.height,columns[3].label('position'),columns[4].label('sync'),func.max(Diver.display_name).label('diver_name'),func.count().label('eligible')).join(Diver,Diver.id==Dive.diver_id).join(UserDiverAccess,(UserDiverAccess.diver_id==Dive.diver_id)&(UserDiverAccess.user_id==user.id)&(UserDiverAccess.access_kind=='OWNER')).where(Dive.dive_code==code)
    if after:
        try:
            key=json.loads(after)
            if not isinstance(key,list) or len(key)!=5 or type(key[0]) is not int or any(not isinstance(v,str) for v in key[1:4]) or type(key[4]) is not bool:raise ValueError()
        except (ValueError,TypeError):raise HTTPException(422,'Invalid context cursor')
        stmt=stmt.where(tuple_(*columns)>tuple(key))
    rows=db.execute(stmt.group_by(*columns).order_by(*columns).limit(51)).mappings().all()
    items=[dict(r,code=code) for r in rows[:50]]
    cursor=json.dumps([rows[49][key] for key in ('diver_id','apparatus','height','position','sync')]) if len(rows)>50 else None
    return {'items':items,'next':cursor}
