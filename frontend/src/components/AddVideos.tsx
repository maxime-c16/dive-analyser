import { useModalOverlay } from '../utils/overlays'
import { useEffect, useRef, useState } from 'react'
import { api } from '../services/api'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { performanceLabel } from '../utils/attemptPresentation'
import { EVALUATION_PROMPT_MAX } from '../services/evaluationApi'

function localDate(date: Date) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

function newUploadId() {
  if (typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  // LAN development can run over HTTP; getRandomValues remains available.
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  bytes[6] = (bytes[6] & 15) | 64
  bytes[8] = (bytes[8] & 63) | 128
  const hex = Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('')
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
}

type Clip = { file: File; id: string; date: string; code: string; height: string; rating: string; notes: string; public: boolean; evaluation: boolean; evaluationPrompt: string }

export default function AddVideos({ onAdded }: { onAdded: () => void }) {
  const { t } = useTranslation()
  const { user } = useAuth()
  const owners = user?.divers.filter(binding => binding.access_kind === 'OWNER') || []
  const input = useRef<HTMLInputElement>(null)
  const trigger = useRef<HTMLButtonElement>(null)
  const [clips, setClips] = useState<Clip[]>([])
  const [index, setIndex] = useState(0)
  const [diver, setDiver] = useState('')
  const [busy, setBusy] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [preview, setPreview] = useState('')
  const [saved, setSaved] = useState(0)
  const form = useRef<HTMLFormElement>(null)
  const overlayRef = useRef<HTMLDivElement>(null)
  const stop = () => { if (!busy && window.confirm(t('addVideos.confirmStop'))) { setClips([]); onAdded() } }
  const clip = clips[index]
  useModalOverlay(form, { enabled: !!clip, isolationRef: overlayRef, onClose: stop, returnFocus: () => trigger.current,
    initialFocus: () => form.current?.querySelector<HTMLInputElement>('input[placeholder="103B"]') ?? null,
  })
  useEffect(() => {
    if (!clip) { setPreview(''); return }
    const url = URL.createObjectURL(clip.file)
    setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [clip?.file])
  useEffect(() => {
    if (!clips.length) return
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [clips.length])
  useEffect(() => {
    if (clip && !busy) form.current?.querySelector<HTMLInputElement>('input[placeholder="103B"]')?.focus()
  }, [index, !!clip, busy])
  if (!owners.length) return null
  const patch = (value: Partial<Clip>) => setClips(current => current.map((item, i) => i === index ? { ...item, ...value } : item))
  const finish = (count = saved) => { setClips([]); setIndex(0); setNotice(t('addVideos.noticeAdded', { count })); onAdded() }
  const save = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!clip || busy) return
    setBusy(true); setError(''); setProgress(0)
    const body = { filename: clip.file.name, dive_code: clip.code.toUpperCase(), height: clip.height, performance: clip.rating, notes: clip.notes, visibility: clip.public ? 'public' : 'private', dive_datetime: new Date(clip.date).toISOString(), diver_id: Number(diver), upload_id: clip.id, evaluation_requested: clip.evaluation, evaluation_prompt: clip.evaluation ? clip.evaluationPrompt.trim() : '' }
    try {
      const reserved = await api.post('/api/v1/dives/uploads', body)
      let job = reserved.data
      if (job.status === 'receiving') {
        job = (await api.put(`/api/v1/dives/uploads/${clip.id}/content`, clip.file, { headers: { 'Content-Type': 'application/octet-stream' }, onUploadProgress: event => setProgress(Math.round(100 * event.loaded / (event.total || clip.file.size))) })).data
      }
      setProgress(100)
      while (job.status === 'queued' || job.status === 'processing' || job.status === 'receiving' || job.status === 'uploading') {
        await new Promise(resolve => setTimeout(resolve, 2000))
        job = (await api.get(`/api/v1/dives/uploads/${clip.id}`)).data
      }
      if (job.status !== 'ready') throw new Error(job.error || t('addVideos.errorAdd'))
      setSaved(current => current + 1)
      if (index + 1 === clips.length) finish(saved + 1)
      else setIndex(current => current + 1)
    } catch (error: any) {
      setError(typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message || t('addVideos.errorAdd'))
    } finally { setBusy(false) }
  }
  return <>
    <input ref={input} type="file" accept="video/*,.mov,.mp4,.m4v,.webm" multiple className="hidden" aria-label={t('addVideos.selectVideos')} onChange={event => {
      const selected = Array.from(event.target.files || [])
      event.target.value = ''
      if (!selected.length) return
      if (selected.some(file => file.size > 1024 ** 3 || file.size === 0)) { setNotice(t('addVideos.sizeNotice')); return }
      setClips(selected.map(file => ({ file, id: newUploadId(), date: localDate(new Date(file.lastModified || Date.now())), code: '', height: '3m', rating: 'M', notes: '', public: false, evaluation: false, evaluationPrompt: '' })))
      setIndex(0); setSaved(0); setDiver(String(owners[0].diver_id)); setNotice(''); setError('')
    }} />
    <button ref={trigger} type="button" className="touch-target inline-flex items-center justify-center whitespace-nowrap border border-app-accent bg-app-accent px-4 text-sm font-semibold text-black hover:bg-app-accent/90" onClick={() => input.current?.click()}>{t('addVideos.add')}</button>
    {notice && <p role="status" className="text-sm text-app-muted">{notice}</p>}
    {clip && <div ref={overlayRef} className="fixed inset-0 z-50 overflow-y-auto bg-black/80 p-3 sm:p-8" role="dialog" aria-modal="true" aria-labelledby="add-video-title">
      <form ref={form} tabIndex={-1} onSubmit={save} className="mx-auto max-w-xl space-y-4 border border-app bg-app-panel p-4 sm:p-6">
        <div className="flex items-center justify-between gap-3"><h2 id="add-video-title" className="text-lg font-semibold">{t("addVideos.videoN", { index: index + 1, total: clips.length })}</h2><button type="button" disabled={busy} onClick={stop}>{t("common.close")}</button></div>
        <p className="break-all text-sm text-app-muted">{clip.file.name}</p>
        <video key={preview} src={preview} controls playsInline preload="metadata" className="max-h-64 w-full bg-black" />
        <p className="text-xs text-app-muted">{t("addVideos.addedAs", { name: user?.display_name })}</p>
        <p className="text-xs text-app-muted">{t("addVideos.qualityHint")}</p>
        {owners.length > 1 && <label className="block">{t("addVideos.diver")}<select className="app-input w-full" value={diver} onChange={event => setDiver(event.target.value)} disabled={busy}>{owners.map(owner => <option key={owner.diver_id} value={owner.diver_id}>{t("addVideos.myDiverN", { id: owner.diver_id })}</option>)}</select></label>}
        <fieldset disabled={busy} className="grid grid-cols-2 gap-3">
          <label>{t("addVideos.code")}<input required pattern="(?:[1-5][0-9]{2,3}|6[0-9]{2})[ABCDabcd]" placeholder="103B" className="app-input w-full" value={clip.code} onChange={event => patch({ code: event.target.value.toUpperCase() })} /></label>
          <label>{t("addVideos.height")}<select className="app-input w-full" value={clip.height} onChange={event => patch({ height: event.target.value })}>{['1m', '3m', '5m', '7.5m', '10m'].map(height => <option key={height}>{height}</option>)}</select></label>
          <label>{t("addVideos.rating")}<select className="app-input w-full" value={clip.rating} onChange={event => patch({ rating: event.target.value })}>{['F', 'B', 'M', 'G', 'P'].map(rating => <option key={rating} value={rating}>{performanceLabel(rating)}</option>)}</select></label>
          <label className="col-span-2 sm:col-span-1">{t("addVideos.date")}<input required type="datetime-local" className="app-input w-full" value={clip.date} onChange={event => patch({ date: event.target.value })} /></label>
          <label className="col-span-2">{t("addVideos.notes")}<textarea maxLength={2000} className="app-input w-full" value={clip.notes} onChange={event => patch({ notes: event.target.value })} /></label>
          <label className="col-span-2 flex items-center gap-2"><input type="checkbox" checked={clip.public} onChange={event => patch({ public: event.target.checked })} />{t("addVideos.visibleToCommunity")}</label>
          <label className="col-span-2 flex items-center gap-2"><input type="checkbox" checked={clip.evaluation} onChange={event => patch({ evaluation: event.target.checked })} />{t("addVideos.evaluationRequest")}</label>
          {clip.evaluation && <label className="col-span-2 flex items-center gap-2">{t("addVideos.evaluationPrompt")}
            <textarea maxLength={EVALUATION_PROMPT_MAX} className="app-input w-full" value={clip.evaluationPrompt} onChange={event => patch({ evaluationPrompt: event.target.value })} placeholder={t('addVideos.evaluationPromptPlaceholder')} />
          </label>}
        </fieldset>
        {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
        {busy && <p role="status">{progress < 100 ? t('addVideos.uploading', { progress }) : t('addVideos.preparing')}</p>}
        <div className="flex justify-between gap-3"><button type="button" disabled={busy} onClick={() => index + 1 === clips.length ? finish() : setIndex(current => current + 1)}>{t("addVideos.skip")}</button><button disabled={busy} className="touch-target border border-app-accent px-4 text-app-accent">{busy ? t('addVideos.adding') : index + 1 === clips.length ? t('addVideos.saveAndFinish') : t('addVideos.saveAndNext')}</button></div>
      </form>
    </div>}
  </>
}
