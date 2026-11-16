"""Independent adjustments reuse isolated tracks; legacy history is never auto-reinterpreted."""
from datetime import datetime
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text, func, tuple_
from sqlalchemy.orm import Session, aliased
from app.database import get_db
from app.models.dive import Dive
from app.models.technique_history import TechniqueTrack, Technique, TechniqueEpisode, TechniqueRevision
from app.services.technique_history import FAMILIES
from .technique_history import ContextInput, Change, owner, snapshot, local_boundary, require_technique_auth_enabled

router=APIRouter(prefix='/technique-adjustments',tags=['technique-history'],
                 dependencies=[Depends(require_technique_auth_enabled)])

def revision(db,diver):
    return int(db.scalar(select(func.coalesce(func.sum(TechniqueTrack.revision),0)+func.count()).where(TechniqueTrack.diver_id==diver)))

def target(db,diver,context,episode_id):
    e=db.scalar(select(TechniqueEpisode).join(TechniqueTrack).where(TechniqueTrack.diver_id==diver,TechniqueEpisode.id==episode_id,TechniqueEpisode.deleted.is_(False)))
    family=context.code[:2] if context.code.startswith('5') else context.code[:1]
    if family not in FAMILIES:family=context.code
    if not e or e.gap or e.scope not in (context.code,family) or e.apparatus!=context.apparatus or e.height!=context.height or (e.position is not None and e.position!=context.position) or (e.sync is not None and e.sync!=context.sync):raise HTTPException(404,'Adjustment unavailable in this context')
    return e

class Browse(ContextInput):
    after:int=Field(default=0,ge=0)

@router.post('/{diver}/list')
def listing(diver:int,body:Browse,request:Request,db:Session=Depends(get_db)):
    owner(request,db,diver,True)
    family=body.code[:2] if body.code.startswith('5') else body.code[:1]
    if family not in FAMILIES:family=body.code
    filters=[TechniqueTrack.diver_id==diver,TechniqueEpisode.deleted.is_(False),TechniqueEpisode.gap.is_(False),TechniqueEpisode.scope.in_([body.code,family]),TechniqueEpisode.apparatus==body.apparatus,TechniqueEpisode.height==body.height,(TechniqueEpisode.position.is_(None))|(TechniqueEpisode.position==body.position),(TechniqueEpisode.sync.is_(None))|(TechniqueEpisode.sync==body.sync)]
    # A copied family applies elsewhere, excluding its original exact-code context.
    original=aliased(TechniqueEpisode)
    filters.append(~((TechniqueTrack.name.like('adjustment-copy-%')) & select(original.id).where(original.id==TechniqueEpisode.source_episode_id,original.scope==body.code,original.apparatus==body.apparatus,original.height==body.height).exists()))
    if body.after:
        cursor=target(db,diver,body,body.after)
        filters.append(tuple_(TechniqueEpisode.start_at,TechniqueEpisode.start_id,TechniqueEpisode.id)<(cursor.start_at,cursor.start_id,cursor.id))
    rows=db.execute(select(TechniqueEpisode,Technique.label,TechniqueTrack.revision).join(TechniqueTrack,TechniqueEpisode.track_id==TechniqueTrack.id).join(Technique,TechniqueEpisode.technique_id==Technique.id).where(*filters).order_by(TechniqueEpisode.start_at.desc(),TechniqueEpisode.start_id.desc(),TechniqueEpisode.id.desc()).limit(51)).all()
    return {'revision':revision(db,diver),'items':[dict(snapshot(e),label=label,track_revision=r) for e,label,r in rows[:50]],'next':rows[49][0].id if len(rows)>50 else None}

class AdjustmentChange(Change):
    draft_identity:str=Field(default='',max_length=80)
    draft_key:str=Field(min_length=1,max_length=160)
    replace_episode_id:int|None=None
    replace_draft_key:str|None=Field(default=None,max_length=160)

class Batch(BaseModel):
    revision:int
    changes:list[AdjustmentChange]=Field(min_length=1,max_length=16)

def normalize(db,diver,c):
    if c.gap:raise HTTPException(422,'An adjustment requires a label')
    if not c.label.strip():raise HTTPException(422,'Adjustment label required')
    if c.anchor_id:
        a=db.execute(select(Dive.id,Dive.history_occurred_at).where(Dive.id==c.anchor_id,Dive.diver_id==diver,Dive.dive_code==c.code,Dive.platform_type==c.apparatus,Dive.height==c.height,func.coalesce(Dive.position,'')==c.position,func.coalesce(Dive.is_sync,False)==c.sync)).one_or_none()
        if a is None:raise HTTPException(404,'Anchor unavailable')
        c.start_at=a.history_occurred_at;c.start_id=a.id
    elif not c.normalized:
        c.start_at=local_boundary(c.start_at,c.timezone)
        c.uncertain_until=local_boundary(c.uncertain_until,c.timezone)
    c.normalized=True
    if c.start_at.tzinfo or (c.uncertain_until and (c.uncertain_until.tzinfo or c.uncertain_until<=c.start_at)):raise HTTPException(422,'Invalid start or uncertainty')

def prepare(db,diver,body,request):
    owner(request,db,diver,True)
    if revision(db,diver)!=body.revision:raise HTTPException(409,'History changed; refresh preview')
    keys=set();starts=set();context=None;changed=set();replaced=set();items=[];by_key={}
    for i,c in enumerate(body.changes):
        normalize(db,diver,c)
        key=(c.code,c.apparatus,c.height,c.position,c.sync)
        if context is not None and key!=context:raise HTTPException(422,'Choose one context')
        context=key
        if c.draft_key in keys:raise HTTPException(422,'Duplicate draft marker')
        keys.add(c.draft_key)
        signature=(*key,c.start_at,c.start_id,c.label.strip().casefold())
        if signature in starts:raise HTTPException(422,'An identical adjustment already starts here in this draft')
        starts.add(signature)
        e=target(db,diver,c,c.episode_id) if c.episode_id else None
        if not e:
            duplicate=db.scalar(select(TechniqueEpisode.id).join(TechniqueTrack,TechniqueEpisode.track_id==TechniqueTrack.id).join(Technique,TechniqueEpisode.technique_id==Technique.id).where(TechniqueTrack.diver_id==diver,TechniqueEpisode.deleted.is_(False),TechniqueEpisode.scope==c.code,TechniqueEpisode.apparatus==c.apparatus,TechniqueEpisode.height==c.height,TechniqueEpisode.position.is_not_distinct_from(c.position),TechniqueEpisode.sync.is_not_distinct_from(c.sync),TechniqueEpisode.start_at==c.start_at,TechniqueEpisode.start_id==c.start_id,func.lower(func.trim(Technique.label))==c.label.strip().lower()).limit(1))
            if duplicate:raise HTTPException(409,'An identical adjustment already starts here; refresh history')
        if e and e.id in changed:raise HTTPException(422,'Adjustment edited twice')
        if e:changed.add(e.id)
        if e and e.end_at and (c.start_at,c.start_id)>=(e.end_at,e.end_id):raise HTTPException(422,'Start must precede the end')
        if e and (c.replace_episode_id or c.replace_draft_key):raise HTTPException(422,'Edit or replace, not both')
        if c.replace_episode_id and c.replace_draft_key:raise HTTPException(422,'Choose one adjustment to replace')
        old=target(db,diver,c,c.replace_episode_id) if c.replace_episode_id else None
        if old:
            if old.id in replaced or old.id in changed or e:raise HTTPException(422,'Conflicting replacement')
            if (c.start_at,c.start_id)<=(old.start_at,old.start_id) or (old.end_at is not None and (c.start_at,c.start_id)>=(old.end_at,old.end_id)):raise HTTPException(422,'Replacement must start while the adjustment is active')
            replaced.add(old.id)
        previous=by_key.get(c.replace_draft_key) if c.replace_draft_key else None
        if c.replace_draft_key:
            if not previous or previous['end_at'] is not None or (c.start_at,c.start_id)<=(previous['start_at'],previous['start_id']):raise HTTPException(422,'Choose an earlier active draft adjustment')
            previous['end_at']=c.start_at;previous['end_id']=c.start_id;previous['next_label']=c.label
        item={'draft_key':c.draft_key,'anchor_id':c.anchor_id,'start_at':c.start_at,'start_id':c.start_id,'end_at':e.end_at if e else None,'end_id':e.end_id if e else None,'next_label':None,'replaces':db.scalar(select(Technique.label).where(Technique.id==old.technique_id)) if old else (previous['label'] if previous else None),'label':c.label,'following':None}
        items.append(item);by_key[c.draft_key]=item
    if changed & replaced:raise HTTPException(422,'Cannot edit and replace the same adjustment')
    for c,item in zip(body.changes,items):
        item['counts']=dict(db.execute(text("""SELECT count(*) affected,count(*) FILTER(WHERE EXISTS(SELECT 1 FROM technique_assignments a JOIN technique_tracks t ON t.id=a.track_id WHERE a.dive_id=dives.id AND t.diver_id=:diver)) explicit_preserved FROM dives WHERE diver_id=:diver AND dive_code=:code AND platform_type=:apparatus AND height=:height AND coalesce(position,'')=:position AND coalesce(is_sync,false)=:sync AND (history_occurred_at,id)>=(:start_at,:start_id) AND (:end_at IS NULL OR (history_occurred_at,id)<(:end_at,:end_id))"""),dict(c.model_dump(),diver=diver,end_at=item['end_at'],end_id=item['end_id'])).mappings().one())
    return items

@router.post('/{diver}/preview')
def preview(diver:int,body:Batch,request:Request,db:Session=Depends(get_db)):
    return {'revision':body.revision,'items':prepare(db,diver,body,request)}

def record(db,track,user,before,e):
    track.revision+=1
    db.add(TechniqueRevision(track_id=track.id,revision=track.revision,author_id=user.id,operation='adjustment',before=before,after=snapshot(e)))
    db.flush()

def detach(db,e,user):
    old=db.get(TechniqueTrack,e.track_id)
    sibling=db.scalar(select(TechniqueEpisode.id).where(TechniqueEpisode.track_id==old.id,TechniqueEpisode.id!=e.id,TechniqueEpisode.deleted.is_(False)).limit(1))
    if not sibling:return old
    before=snapshot(e);label=db.scalar(select(Technique.label).where(Technique.id==e.technique_id))
    track=TechniqueTrack(diver_id=old.diver_id,name='adjustment-'+uuid4().hex);db.add(track);db.flush()
    t=Technique(track_id=track.id,label=label);db.add(t);db.flush()
    # Preserve conflicting identities too, without materializing assignments or
    # mapping by label (distinct techniques may deliberately share a label).
    db.execute(text("""WITH identity_map AS MATERIALIZED (
      SELECT t.id old_id,nextval(pg_get_serial_sequence('techniques','id')) new_id,t.label,t.created_at
      FROM techniques t WHERE t.track_id=:old AND t.id<>:old_tech
      AND EXISTS(SELECT 1 FROM technique_assignments a
        WHERE a.track_id=:old AND a.episode_id=:episode AND a.technique_id=t.id)
    ), cloned AS (
      INSERT INTO techniques(id,track_id,label,created_at)
      SELECT new_id,:new,label,created_at FROM identity_map RETURNING id
    )
    INSERT INTO technique_assignments(track_id,dive_id,diver_id,code,apparatus,height,position,sync,state,technique_id,episode_id)
    SELECT :new,a.dive_id,a.diver_id,a.code,a.apparatus,a.height,a.position,a.sync,a.state,
      CASE WHEN a.technique_id=:old_tech THEN :new_tech ELSE c.id END,a.episode_id
    FROM technique_assignments a LEFT JOIN identity_map m ON m.old_id=a.technique_id
    LEFT JOIN cloned c ON c.id=m.new_id
    WHERE a.track_id=:old AND a.episode_id=:episode"""),dict(new=track.id,old=old.id,episode=e.id,old_tech=e.technique_id,new_tech=t.id))
    # A legacy session flag belongs to the old track. Preserve it for sessions
    # intersecting this episode; membership still uses the episode's interval.
    db.execute(text("""INSERT INTO technique_session_states(track_id,session_id,code,apparatus,height,position,sync,state)
    SELECT :new,s.session_id,s.code,s.apparatus,s.height,s.position,s.sync,s.state FROM technique_session_states s
    WHERE s.track_id=:old AND (s.code=:scope OR (:family AND s.code LIKE :scope || '%')) AND EXISTS(SELECT 1 FROM dives d WHERE d.diver_id=:diver AND d.session_id=s.session_id
    AND d.dive_code=s.code AND d.platform_type=:apparatus AND d.height=:height
    AND (:position IS NULL OR d.position=:position) AND (:sync IS NULL OR d.is_sync=:sync)
    AND (d.history_occurred_at,d.id)>=(:start_at,:start_id) AND (:end_at IS NULL OR (d.history_occurred_at,d.id)<(:end_at,:end_id)))
    ON CONFLICT DO NOTHING"""),dict(new=track.id,old=old.id,diver=old.diver_id,scope=e.scope,family=e.scope in FAMILIES,apparatus=e.apparatus,height=e.height,position=e.position,sync=e.sync,start_at=e.start_at,start_id=e.start_id,end_at=e.end_at,end_id=e.end_id))
    e.track_id=track.id;e.technique_id=t.id;record(db,old,user,before,e)
    return track

@router.post('/{diver}/save')
def save(diver:int,body:Batch,request:Request,db:Session=Depends(get_db)):
    try:
        impacts=prepare(db,diver,body,request);user=owner(request,db,diver,True);result=[]
        for c,item in zip(body.changes,impacts):
            if c.replace_episode_id:
                old=target(db,diver,c,c.replace_episode_id);before=snapshot(old);old.end_at=c.start_at;old.end_id=c.start_id;record(db,db.get(TechniqueTrack,old.track_id),user,before,old)
            if c.episode_id:
                e=target(db,diver,c,c.episode_id);before=snapshot(e);track=detach(db,e,user)
                e.start_at=c.start_at;e.start_id=c.start_id;e.anchor_id=c.anchor_id;e.uncertain_until=c.uncertain_until;e.precision=c.precision
                current=db.get(Technique,e.technique_id)
                if current.label!=c.label.strip():
                    current=Technique(track_id=track.id,label=c.label.strip());db.add(current);db.flush();e.technique_id=current.id
            else:
                track=TechniqueTrack(diver_id=diver,name='adjustment-'+uuid4().hex);db.add(track);db.flush()
                t=Technique(track_id=track.id,label=c.label.strip());db.add(t);db.flush()
                e=TechniqueEpisode(track_id=track.id,technique_id=t.id,scope=c.code,apparatus=c.apparatus,height=c.height,position=c.position,sync=c.sync,start_at=c.start_at,start_id=c.start_id,end_at=item['end_at'],end_id=item['end_id'],uncertain_until=c.uncertain_until,anchor_id=c.anchor_id,precision=c.precision,timezone=c.timezone,gap=False,notes=c.notes)
                db.add(e);db.flush();before={}
            record(db,track,user,before,e);result.append(snapshot(e))
        db.commit();return {'revision':revision(db,diver),'episodes':result}
    except Exception:
        db.rollback();raise

class End(ContextInput):
    revision:int
    episode_id:int
    end_at:datetime|None=None
    end_id:int=0
    timezone:str=Field(default='UTC',max_length=80)
    resume:bool=False
    commit:bool=False

@router.post('/{diver}/end')
def end(diver:int,body:End,request:Request,db:Session=Depends(get_db)):
    try:
        user=owner(request,db,diver,True)
        if revision(db,diver)!=body.revision:raise HTTPException(409,'History changed; refresh preview')
        e=target(db,diver,body,body.episode_id)
        until=None if body.resume else local_boundary(body.end_at,body.timezone)
        if not body.resume and (not until or (until,body.end_id)<=(e.start_at,e.start_id)):raise HTTPException(422,'End must follow the start')
        if not body.commit:return {'revision':body.revision,'end_at':until,'resume':body.resume}
        before=snapshot(e);track=detach(db,e,user)
        e.end_at=until;e.end_id=None if body.resume else body.end_id
        record(db,track,user,before,e);db.commit();return {'revision':revision(db,diver)}
    except Exception:
        db.rollback();raise


class Remove(ContextInput):
    revision:int
    episode_id:int
    commit:bool=False

@router.post('/{diver}/remove')
def remove(diver:int,body:Remove,request:Request,db:Session=Depends(get_db)):
    try:
        user=owner(request,db,diver,True)
        if revision(db,diver)!=body.revision:raise HTTPException(409,'History changed; refresh preview')
        e=target(db,diver,body,body.episode_id)
        if not body.commit:return {'revision':body.revision,'episode_id':e.id}
        before=snapshot(e);e.deleted=True
        record(db,db.get(TechniqueTrack,e.track_id),user,before,e);db.commit()
        return {'revision':revision(db,diver)}
    except Exception:
        db.rollback();raise

from .technique_history import CopyTarget
class Copy(ContextInput):
    revision:int
    episode_id:int
    targets:list[CopyTarget]=Field(min_length=1,max_length=16)
    commit:bool=False

@router.post('/{diver}/copy')
def copy(diver:int,body:Copy,request:Request,db:Session=Depends(get_db)):
    try:
        user=owner(request,db,diver,True)
        if revision(db,diver)!=body.revision:raise HTTPException(409,'History changed; refresh preview')
        source=target(db,diver,body,body.episode_id)
        if len({(t.scope,t.apparatus,t.height) for t in body.targets})!=len(body.targets):raise HTTPException(422,'Duplicate targets')
        from app.models.dive_code import DiveCode
        for destination in body.targets:
            if destination.scope not in FAMILIES and not db.scalar(select(DiveCode.dive_code).where(DiveCode.dive_code==destination.scope).limit(1)):raise HTTPException(422,'Unknown exact code')
            if destination.apparatus==source.apparatus and destination.height==source.height and (destination.scope==source.scope or source.scope in FAMILIES and destination.scope.startswith(source.scope)):raise HTTPException(422,'Already applies to this context')
            if db.scalar(select(TechniqueEpisode.id).join(TechniqueTrack,TechniqueEpisode.track_id==TechniqueTrack.id).where(TechniqueTrack.diver_id==diver,TechniqueEpisode.source_episode_id==source.id,TechniqueEpisode.scope==destination.scope,TechniqueEpisode.apparatus==destination.apparatus,TechniqueEpisode.height==destination.height,TechniqueEpisode.deleted.is_(False)).limit(1)):raise HTTPException(409,'Already copied to this context')
        if not body.commit:
            preview=[]
            for destination in body.targets:
                counts=db.execute(text("""SELECT count(*) affected FROM dives d WHERE d.diver_id=:diver
                AND ((:family AND d.dive_code LIKE :scope || '%') OR (NOT :family AND d.dive_code=:scope))
                AND d.platform_type=:apparatus AND d.height=:height
                AND (:position IS NULL OR d.position=:position) AND (:sync IS NULL OR coalesce(d.is_sync,false)=:sync)
                AND (d.history_occurred_at,d.id)>=(:start_at,:start_id) AND (:end_at IS NULL OR (d.history_occurred_at,d.id)<(:end_at,:end_id))
                AND NOT(d.dive_code=:original_scope AND d.platform_type=:original_apparatus AND d.height=:original_height)"""),dict(diver=diver,family=destination.scope in FAMILIES,scope=destination.scope,apparatus=destination.apparatus,height=destination.height,position=source.position,sync=source.sync,start_at=source.start_at,start_id=source.start_id,end_at=source.end_at,end_id=source.end_id,original_scope=source.scope,original_apparatus=source.apparatus,original_height=source.height)).mappings().one()
                preview.append({'target':destination.model_dump(),'counts':dict(counts)})
            return {'revision':body.revision,'targets':[t.model_dump() for t in body.targets],'preview':preview}
        label=db.scalar(select(Technique.label).where(Technique.id==source.technique_id))
        results=[]
        for destination in body.targets:
            track=TechniqueTrack(diver_id=diver,name='adjustment-copy-'+uuid4().hex);db.add(track);db.flush()
            technique=Technique(track_id=track.id,label=label);db.add(technique);db.flush()
            values={name:getattr(source,name) for name in ('position','sync','start_at','start_id','end_at','end_id','uncertain_until','precision','timezone','gap','notes')}
            if values['precision']=='attempt':values['precision']='date'
            e=TechniqueEpisode(**values,track_id=track.id,technique_id=technique.id,scope=destination.scope,apparatus=destination.apparatus,height=destination.height,anchor_id=None,source_episode_id=source.id)
            db.add(e);db.flush();record(db,track,user,{},e);results.append(snapshot(e))
        db.commit();return {'revision':revision(db,diver),'episodes':results}
    except Exception:
        db.rollback();raise
