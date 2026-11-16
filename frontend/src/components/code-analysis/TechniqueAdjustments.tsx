import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'
import { Plus, ChevronRight } from 'lucide-react'
import { api } from '../../services/api'
import TechniqueDialog from './TechniqueDialog'
import TechniqueSetup, {type AdjustmentChoice} from './TechniqueSetup'
import TechniqueTrackChart from './TechniqueTrackChart'
import { techniqueDateTime } from './techniqueDates'
import './techniqueHistory.css'

type Context={code:string;apparatus:string;height:string;position:string;sync:boolean}
type Adjustment=AdjustmentChoice & {track_revision:number;start_id:number;end_id:number|null;uncertain_until:string|null}
const families=['1','2','3','4','51','52','53','54']
const localNow=()=>new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16)
export default function TechniqueAdjustments({diver,context,viewer}:{diver:number;context:Context;viewer:string|number}){
 const {t,i18n}=useTranslation(),base=`/api/v1/technique-adjustments/${diver}`,history=`/api/v1/technique-history/${diver}`
 const [pageAfter,setPageAfter]=useState(0)
 const [items,setItems]=useState<Adjustment[]>([]),[version,setVersion]=useState(0),[next,setNext]=useState<number|null>(null)
 const [track,setTrack]=useState<{id:number;revision:number}|null>(null),[selected,setSelected]=useState<number|null>(null)
 const [loading,setLoading]=useState(true),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('')
 const [setup,setSetup]=useState(false),[editing,setEditing]=useState<Adjustment|undefined>(),[draft,setDraft]=useState(false)
 const [dialog,setDialog]=useState<{mode:'end'|'continue'|'share'|'remove';item:Adjustment}|null>(null),[end,setEnd]=useState(localNow),[reviewed,setReviewed]=useState(false)
 const [scope,setScope]=useState(''),[otherCode,setOtherCode]=useState(''),[shareCount,setShareCount]=useState<number|null>(null)
 const generation=useRef(0),scopeEpoch=useRef(0),mounted=useRef(true),key=JSON.stringify(context)
 const date=(value:string)=>techniqueDateTime(value,i18n.language)
 const timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'
  const draftKey=track?`adjustment-draft:${viewer}:${history}/${track.id}:${key}:new`:''
 async function load(after=0){
  const gen=++generation.current;setLoading(true);setError('')
  try{
   const [list,tracks]=await Promise.all([api.post(`${base}/list`,{...context,after}),api.get(`${history}/tracks`)])
   if(!mounted.current||gen!==generation.current)return
   if(after&&list.data.revision!==version){setError(t('technique.conflict'));return}
   setItems(list.data.items);setPageAfter(after)
   setVersion(list.data.revision);setNext(list.data.next);setTrack(tracks.data.items[0]??null)
  }catch{if(mounted.current&&gen===generation.current)setError(t('technique.unavailable'))}
  finally{if(mounted.current&&gen===generation.current)setLoading(false)}
 }
 useEffect(()=>{mounted.current=true;setItems([]);setSelected(null);setSetup(false);setDialog(null);setBusy(false);setNotice('');void load();return()=>{mounted.current=false;scopeEpoch.current++;generation.current++}},[base,key,viewer])
 useEffect(()=>{try{setDraft(Boolean(draftKey&&localStorage.getItem(draftKey)))}catch{setDraft(false)}},[draftKey,setup])
 async function openSetup(item?:Adjustment){
  if(busy||loading)return
  setBusy(true);setError('');const gen=scopeEpoch.current
  try{
   let current=track
   if(item)current={id:item.track_id,revision:item.track_revision}
   if(!current){const created=await api.post(`${history}/tracks`,{name:'General'});current=created.data;const list=await api.post(`${base}/list`,context);if(!mounted.current||gen!==scopeEpoch.current)return;setVersion(list.data.revision);setTrack(current)}
   if(!mounted.current||gen!==scopeEpoch.current)return
   setEditing(item);setSetup(true)
  }catch{if(mounted.current&&gen===scopeEpoch.current)setError(t('technique.unavailable'))}
  finally{if(mounted.current&&gen===scopeEpoch.current)setBusy(false)}
 }
 async function submitDialog(){
  if(!dialog||busy||loading)return
  const gen=scopeEpoch.current;setBusy(true);setError('')
  try{
   if(dialog.mode==='remove'){
    await api.post(`${base}/remove`,{...context,revision:version,episode_id:dialog.item.id,commit:reviewed},{timeout:30000})
    if(!mounted.current||gen!==scopeEpoch.current)return
    if(!reviewed){setReviewed(true);return}
   }else if(dialog.mode==='share'){
    const {data}=await api.post(`${base}/copy`,{...context,revision:version,episode_id:dialog.item.id,targets:[{scope:scope==='code'?otherCode.trim().toUpperCase():scope,apparatus:context.apparatus,height:context.height}],commit:reviewed},{timeout:30000})
    if(!mounted.current||gen!==scopeEpoch.current)return
    if(!reviewed){setShareCount(data.preview?.[0]?.counts?.affected??null);setReviewed(true);return}
   }else{
    await api.post(`${base}/end`,{...context,revision:version,episode_id:dialog.item.id,resume:dialog.mode==='continue',end_at:dialog.mode==='continue'?null:end,timezone,commit:reviewed},{timeout:30000})
    if(!mounted.current||gen!==scopeEpoch.current)return
    if(!reviewed){setReviewed(true);return}
   }
   setDialog(null);setNotice(t('technique.saved'));void load()
  }catch(failure){if(mounted.current&&gen===scopeEpoch.current){
    const status=(failure as {response?:{status?:number}}).response?.status
    setError(t(status===409?'technique.conflict':status===422?(dialog.mode==='end'?'adjustments.invalidEnd':'adjustments.invalidChange'):'technique.unavailable'));setReviewed(false)
   }}
  finally{if(mounted.current&&gen===scopeEpoch.current)setBusy(false)}
 }
 const active=(item:Adjustment)=>!item.end_at&&Date.parse(item.start_at+'Z')<=Date.now()
 function openDialog(mode:'end'|'continue'|'share'|'remove',item:Adjustment){setDialog({mode,item});setEnd(localNow());setReviewed(false);setScope('');setOtherCode('');setShareCount(null);setError('')}
 const renderItem=(item:Adjustment)=><li key={item.id} className={`${active(item)?'is-ongoing ':''}${selected===item.id?'is-selected':''}`}>
  <button className="th-episode" aria-pressed={selected===item.id} onClick={()=>setSelected(selected===item.id?null:item.id)}><span className="th-timeline-dot" aria-hidden="true"/><span className="th-episode-copy"><span className="th-episode-name">{item.label}{active(item)&&<span className="th-current">{t('adjustments.active')}</span>}</span><span className="th-date">{item.uncertain_until?'≈ ':''}{date(item.start_at)}{item.end_at?` → ${date(item.end_at)}`:` · ${t('adjustments.noEnd')}`}</span>{item.scope!==context.code&&<small>{t('technique.appliesTo')} {item.scope}</small>}</span><ChevronRight size={16}/></button>
  {selected===item.id&&<div className="th-episode-actions th-adjustment-actions"><button onClick={()=>void openSetup(item)}>{t('technique.adjustInPlayer')}</button>{active(item)?<button onClick={()=>openDialog('end',item)}>{t('adjustments.stop')}</button>:item.end_at&&<button onClick={()=>openDialog('continue',item)}>{t('adjustments.removeEnd')}</button>}<button onClick={()=>openDialog('share',item)}>{t('technique.share')}</button><button onClick={()=>openDialog('remove',item)}>{t('technique.delete')}</button></div>}
  {selected===item.id&&<TechniqueTrackChart key={item.track_id} base={`${history}/${item.track_id}`} context={context} revision={item.track_revision} selected={item.id} selection={item} onSelect={id=>setSelected(id)} onClear={()=>setSelected(null)}/>}
 </li>
 return <section className="ca-panel th-history th-adjustments" aria-label={t('adjustments.title')}>
  <div className="ca-panel-h"><h2>{t('adjustments.title')}</h2></div>
  <button className="th-primary th-add-adjustment" disabled={busy||loading} onClick={()=>void openSetup()}><Plus size={17}/>{t(draft?'technique.resumeHistory':'adjustments.add')}</button>
  <p className="th-adjustments-rule">{t('adjustments.rule')}</p>
  {error&&<div role="alert" className="th-error">{error}<button className="th-text-button" onClick={()=>void load()}>{t('technique.retry')}</button></div>}
  {notice&&<p role="status" className="th-notice">{notice}</p>}
  {loading&&!items.length&&<p role="status">{t('technique.loadingClips')}</p>}
  
  {items.some(active)&&<><h3 className="th-adjustment-heading">{t('adjustments.active')}</h3><ol className="th-timeline th-adjustment-list">{items.filter(active).map(renderItem)}</ol></>}
  {items.some(item=>!active(item))&&<><h3 className="th-adjustment-heading">{t('adjustments.ended')}</h3><p className="th-adjustments-rule">{t('adjustments.existingEnds')}</p><ol className="th-timeline th-adjustment-list">{items.filter(item=>!active(item)).map(renderItem)}</ol></>}
  {!loading&&!items.length&&<p>{t('adjustments.empty')}</p>}
  {pageAfter>0&&<button className="th-text-button" disabled={loading} onClick={()=>void load()}>{t('adjustments.firstPage')}</button>}
  {next!=null&&<button className="th-text-button" disabled={loading} onClick={()=>void load(next)}>{t('adjustments.more')}</button>}
  {setup&&track&&createPortal(<TechniqueSetup key={`${key}/${editing?.id??'new'}`} viewer={viewer} independent={{base,revision:version,choices:items,more:next!=null,onMore:()=>void load(next??0)}} base={`${history}/${editing?.track_id??track.id}`} revision={editing?.track_revision??track.revision} trackName={t('adjustments.title')} context={context} initialEpisode={editing} constrainPosition={editing?editing.position!=null:true} constrainSync={editing?editing.sync!=null:true} onClose={()=>setSetup(false)} onDone={()=>{setSetup(false);setNotice(t('technique.saved'));void load()}}/>,document.body)}
  {dialog&&<TechniqueDialog title={t(dialog.mode==='remove'?'technique.delete':dialog.mode==='share'?'technique.share':dialog.mode==='end'?'adjustments.stop':'adjustments.removeEnd')} onClose={()=>{if(!busy)setDialog(null)}}>
   <div className="th-form"><strong>{dialog.item.label}</strong>
    {dialog.mode==='remove'?<p>{t('adjustments.removeConfirm')}</p>:dialog.mode==='continue'?<p>{t('adjustments.continueConfirm',{date:date(dialog.item.start_at)})}</p>:dialog.mode==='end'?<label className="th-field">{t('adjustments.endDate')}<input type="datetime-local" value={end} disabled={reviewed||busy} onChange={e=>setEnd(e.target.value)}/></label>:<>
     <label className="th-field">{t('technique.chooseScope')}<select value={scope} disabled={reviewed||busy} onChange={e=>setScope(e.target.value)}><option value="">—</option>{families.map(f=><option key={f} value={f}>{t(`technique.family${f}`)}</option>)}<option value="code">{t('technique.otherCode')}</option></select></label>
     {scope==='code'&&<label className="th-field">{t('technique.otherCode')}<input value={otherCode} maxLength={10} disabled={reviewed||busy} onChange={e=>setOtherCode(e.target.value)}/></label>}<span>{t(context.apparatus==='platform'?'technique.platform':'technique.springboard')} · {context.height} · {dialog.item.position??t('technique.allPositions')} · {t(dialog.item.sync==null?'technique.individualAndSync':dialog.item.sync?'technique.onlySync':'technique.onlyIndividual')} · {t('adjustments.copyOnce')}</span>
     {shareCount!=null&&<p>{t('technique.affectedDives',{count:shareCount})}</p>}
    </>}
    {error&&<div role="alert" className="th-error">{error}<button className="th-text-button" disabled={busy||loading} onClick={()=>{setReviewed(false);void load()}}>{t('technique.retry')}</button></div>}
    {reviewed&&dialog.mode!=='share'&&dialog.mode!=='remove'&&<p>{dialog.mode==='end'?t('adjustments.stopsOnlyThis'):t('adjustments.continues')}</p>}
    <div className="th-dialog-actions"><button className="th-secondary" disabled={busy} onClick={()=>reviewed?setReviewed(false):setDialog(null)}>{t(reviewed?'common.back':'technique.cancel')}</button><button className="th-primary" disabled={busy||loading||(dialog.mode==='end'&&!end)||(dialog.mode==='share'&&(!scope||scope==='code'&&!otherCode.trim()))} onClick={()=>void submitDialog()}>{t(reviewed?'common.save':'technique.reviewChange')}</button></div>
   </div>
  </TechniqueDialog>}
 </section>
}
