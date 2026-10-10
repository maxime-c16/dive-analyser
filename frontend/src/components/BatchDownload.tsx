import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Download, CheckCheck } from 'lucide-react'
import { saveDownloadBatch, startClipDownload, type DownloadClip } from '../services/clipDownloads'

export default function BatchDownload({ batchId, diverId }: { batchId: string; diverId: number | null }) {
  const { t } = useTranslation()
  const [clips, setClips] = useState<DownloadClip[] | null>(null)
  const [error, setError] = useState(false)
  const [downloadError, setDownloadError] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [requested, setRequested] = useState(0)
  const operation = useRef<Promise<DownloadClip[]> | null>(null)
  useEffect(() => {
    let active = true
    let timer: ReturnType<typeof setTimeout> | undefined
    setError(false)
    setDownloadError(false)
    if (diverId === null) { setError(true); return }
    // Share the request across StrictMode's effect replay, and cancel dispatch
    // on unmount so changing account/page cannot keep downloading in background.
    operation.current ??= saveDownloadBatch(batchId, diverId)
    operation.current.then(items => {
      if (!active) return
      setClips(items)
      let index = 0
      const next = () => {
        if (!active || index >= items.length) return
        try { startClipDownload(items[index]) }
        catch { setDownloadError(true); return }
        index++
        setRequested(index)
        timer = setTimeout(next, 1000)
      }
      next()
    }).catch(() => { if (active) { operation.current = null; setError(true) } })
    return () => { active = false; clearTimeout(timer) }
  }, [batchId, diverId, attempt])
  return <div className="app-panel mx-auto mt-8 max-w-xl p-6">
    {clips && <CheckCheck className="h-8 w-8 text-app-accent" aria-hidden />}
    <h1 className="mt-3 text-xl font-semibold">{t(error ? 'downloads.saveFailed' : clips ? 'downloads.saved' : 'downloads.saving')}</h1>
    {error ? <><p role="alert" className="mt-3">{t('downloads.saveError')}</p><button className="touch-target mt-3 border border-app px-4 py-2" onClick={() => setAttempt(value => value + 1)}>{t('downloads.tryAgain')}</button></> : clips && <>
      <p className="mt-2 text-sm text-app-muted" role="status">{t('downloads.progress', { count: requested, total: clips.length })}</p>
      <p className="mt-3 text-sm text-app-muted">{t('downloads.batchHint')}</p>
      {downloadError && <p className="mt-3 text-sm" role="alert">{t('downloads.automaticError')}</p>}
      <div className="mt-4 grid gap-2">{clips.map(clip => <a key={clip.id} href={clip.url} download={clip.name} className="touch-target inline-flex items-center gap-2 border border-app px-3 py-2"><Download size={18} />{clip.name}</a>)}</div>
    </>}
    <Link to="/dives" className="touch-target mt-5 inline-block text-app-accent">{t('deposits.backToLibrary')}</Link>
  </div>
}
