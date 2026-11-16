import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import DiveThumbnail from '../DiveThumbnail'
import { techniqueDate } from './techniqueDates'
export type TechniqueSession = { session_id:number; first_id:number; first_at:string; last_at:string; video_uuid:string|null; attempts:number; scored:number; median:number|null; location:string|null; technique_label:string|null; techniques:number }
export default function TechniqueSessionBrowser({base,context,revision,onChoose,onReview,count,initialPage,onPageChange,onRevision,exactOnly=false,hideTechnique=false}:{base:string;context:object;revision:number;onChoose:(session:TechniqueSession,exact:boolean,approximate?:boolean)=>void;onReview:()=>void;count:number;hideTechnique?:boolean;exactOnly?:boolean;initialPage?:{month:string;after:number};onPageChange?:(page:{month:string;after:number})=>void;onRevision?:(revision:number)=>void}) {
 const {t,i18n}=useTranslation()
 const [items,setItems]=useState<TechniqueSession[]>([]),[months,setMonths]=useState<{month:string;sessions:number}[]>([])
 const [month,setMonth]=useState(initialPage?.month??''),[after,setAfter]=useState(initialPage?.after??0),[next,setNext]=useState<number|null>(null),[selected,setSelected]=useState<number|null>(null)
 const [loading,setLoading]=useState(true),[error,setError]=useState(''),[retry,setRetry]=useState(0)
 const key=JSON.stringify(context)
 const [expectedRevision,setExpectedRevision]=useState(revision)
 useEffect(()=>{onPageChange?.({month,after})},[month,after,onPageChange])
 useEffect(()=>{
  let current=true;const controller=new AbortController();setLoading(true);setError('');setSelected(null)
  api.post(`${base}/browse-sessions`,{...context,after,month},{signal:controller.signal}).then(({data})=>{
   if(!current)return
   if(data.revision!==expectedRevision){setError(t('technique.conflict'));return}
   setItems(data.items);setMonths(data.months);setNext(data.next)
  }).catch(()=>{if(current&&!controller.signal.aborted)setError(t('technique.unavailable'))}).finally(()=>{if(current)setLoading(false)})
  return()=>{current=false;controller.abort()}
 },[base,key,expectedRevision,after,month,retry,t])
 return <div className="th-session-browser">
  <div className="th-session-browser-head"><h3>{t('technique.chooseSession')}</h3>{count>0&&<button className="th-primary" onClick={onReview}>{t('technique.reviewMarkers',{count})}</button>}</div>
  <label className="th-field">{t('technique.month')}<select value={month} onChange={e=>{setMonth(e.target.value);setAfter(0)}}><option value="">{t('technique.allMonths')}</option>{months.map(m=><option key={m.month} value={m.month}>{new Intl.DateTimeFormat(i18n.language,{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(m.month+'-01T12:00:00Z'))}</option>)}</select></label>
  {error?<div><p role="alert" className="th-error">{error}</p><button className="th-secondary" onClick={async()=>{try{const {data}=await api.get(`${base}/revisions`);setExpectedRevision(data.revision);onRevision?.(data.revision);setRetry(n=>n+1)}catch{setError(t('technique.unavailable'))}}}>{t('technique.retry')}</button></div>:loading?<p role="status">{t('technique.loadingClips')}</p>:<>
  <ol className="th-session-cards">{items.map((s,index)=><li key={s.session_id}>
   {(index===0||items[index-1].first_at.slice(0,7)!==s.first_at.slice(0,7))&&<h4>{new Intl.DateTimeFormat(i18n.language,{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(s.first_at+'Z'))}</h4>}
   <button className="th-session-card" aria-expanded={selected===s.session_id} onClick={()=>setSelected(selected===s.session_id?null:s.session_id)}>
    <span className="th-session-poster"><DiveThumbnail dive={{dive_code:(context as {code:string}).code,video_uuid:s.video_uuid}} compact/></span>
    <span><strong>{techniqueDate(s.first_at,i18n.language)}</strong><small>{t('technique.sessionDiveCount',{count:s.attempts})}{s.location?` · ${s.location}`:''}</small>{!hideTechnique&&<small>{s.techniques>1?t('technique.severalTechniques'):s.technique_label??t('technique.unrecorded')}</small>}</span>
   </button>
   {selected===s.session_id&&<div className="th-session-choices">{!exactOnly&&<button className="th-primary" onClick={()=>onChoose(s,false)}>{t('technique.fromSessionStart')}</button>}<button className="th-secondary" onClick={()=>onChoose(s,true)}>{t('technique.findExactDive')}</button>{!exactOnly&&<button className="th-text-button" onClick={()=>onChoose(s,false,true)}>{t('technique.aroundSession')}</button>}</div>}
  </li>)}</ol>
  {!items.length&&<p>{t('technique.noClips')}</p>}
  <div className="th-pagination">{after>0&&<button onClick={()=>setAfter(0)}>{t('common.back')}</button>}{next!=null&&<button onClick={()=>setAfter(next)}>{t('technique.olderSessions')}</button>}</div>
  </>}
 </div>
}
