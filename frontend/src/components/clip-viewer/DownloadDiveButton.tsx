import { useState } from 'react'
import { Download, X, Share2 } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { createPortal } from 'react-dom'
import { useRef } from 'react'
import { useModalOverlay } from '../../utils/overlays'
import { clipDownloadUrl, startClipDownload } from '../../services/clipDownloads'

export default function DownloadDiveButton({ id }: { id: number }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const sheet = useRef<HTMLDivElement>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  useModalOverlay(sheet, { enabled: open, layer: 70, extraRef: backdrop, onClose: () => setOpen(false), returnFocus: () => trigger.current })
  const clip = { id, name: `dive-${id}.mp4`, url: clipDownloadUrl(id) }
  const supportsFiles = typeof navigator.canShare === 'function' && typeof navigator.share === 'function'
  return <>
    <button ref={trigger} type="button" aria-label={t('downloads.download')} onClick={() => {
      startClipDownload(clip)
      setOpen(true)
    }}><Download size={25} /><span>{t('downloads.short')}</span></button>
    {open && createPortal(<div ref={backdrop} className="clip-share-backdrop" onClick={event => { if (event.target === event.currentTarget) setOpen(false) }}>
      <div ref={sheet} className="clip-share-sheet" role="dialog" aria-modal="true" aria-label={t('downloads.download')} tabIndex={-1}>
        <header className="clip-share-sheet-heading"><h2>{t('downloads.requested')}</h2><button type="button" className="clip-share-close" onClick={() => setOpen(false)} aria-label={t('downloads.close')}><X size={20} /></button></header>
        <p className="clip-share-dm-hint">{t('downloads.deviceHint')}</p>
        <button className="clip-share-copy" type="button" onClick={() => startClipDownload(clip)}><Download size={22} />{t('downloads.retry')}</button>
        {supportsFiles && <button className="clip-share-copy" type="button" disabled={busy} onClick={async () => {
          setError(false)
          // Preparing the file is a separate click so sharing retains activation.
          if (file) {
            try { await navigator.share({ files: [file] }) }
            catch (reason) { if (!(reason instanceof DOMException && reason.name === 'AbortError')) setError(true) }
            return
          }
          setBusy(true)
          try {
            const response = await fetch(`${clip.url}?for_share=true`, { credentials: 'same-origin' })
            if (!response.ok) throw new Error('Unavailable')
            const blob = await response.blob()
            if (!blob.type.startsWith('video/')) throw new Error('Unavailable')
            const suffix = blob.type.includes('quicktime') ? 'mov' : blob.type.includes('webm') ? 'webm' : 'mp4'
            const filename = /filename="(dive-[\w.-]+)"/.exec(response.headers.get('content-disposition') || '')?.[1]
            const prepared = new File([blob], filename || `dive-${id}.${suffix}`, { type: blob.type })
            if (!navigator.canShare({ files: [prepared] })) throw new Error('Unsupported')
            setFile(prepared)
          } catch { setError(true) }
          finally { setBusy(false) }
        }}><Share2 size={22} />{t(busy ? 'downloads.preparing' : file ? 'downloads.photos' : 'downloads.preparePhotos')}</button>}
        {error && <p role="alert">{t('downloads.photosError')}</p>}
      </div>
    </div>, document.body)}
  </>
}
