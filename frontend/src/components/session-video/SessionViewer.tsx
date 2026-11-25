import { useId, useLayoutEffect, useRef, type ReactNode, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { ChevronLeft, ChevronRight, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { sessionVideoPaths, type SessionVideoInfo } from '../../services/sessionVideosApi'
import { useModalOverlay } from '../../utils/overlays'
import SessionVideoPlayer from './SessionVideoPlayer'

type Props = {
  video: SessionVideoInfo
  guestBase?: string
  opener: RefObject<HTMLButtonElement>
  fallbackFocus: () => HTMLElement | null
  onClose: () => void
  hidden: boolean
  error: string
  batch?: ReactNode
  download: ReactNode
  downloadFallback: ReactNode
  restoreDownloadFocus?: () => void
  navigation?: {
    position: number
    total: number
    loading: boolean
    previous?: () => void
    next?: () => void
  }
}

export default function SessionViewer({
  video, guestBase, opener, fallbackFocus, onClose, hidden, error, batch, download, downloadFallback, restoreDownloadFocus, navigation,
}: Props) {
  const { t } = useTranslation()
  const heading = useRef<HTMLHeadingElement>(null)
  const viewer = useRef<HTMLDivElement>(null)
  const title = useId()
  useModalOverlay(viewer, {
    layer: 60, onClose, fallbackFocus,
    initialFocus: () => heading.current, returnFocus: () => opener.current,
  })
  useLayoutEffect(() => {
    heading.current?.focus({ preventScroll: true })
  }, [video.id])
  useLayoutEffect(() => {
    if (restoreDownloadFocus) {
      viewer.current?.querySelector<HTMLElement>('[data-download-target]')?.focus({ preventScroll: true })
      restoreDownloadFocus()
    }
  }, [restoreDownloadFocus])

  const paths = sessionVideoPaths(video.id)
  const playUrl = guestBase ? (video as SessionVideoInfo & { video_url: string }).video_url : paths.play
  const reportUrl = guestBase ? `${guestBase}/videos/${video.id}/playback-issues` : paths.report
  return createPortal(<div ref={viewer} className="session-viewer" role="dialog" aria-modal="true"
    aria-labelledby={title} tabIndex={-1} aria-hidden={hidden || undefined}>
    <header className="session-viewer-header">
      <button type="button" className="session-viewer-control" aria-label={t('sessionVideo.closePlayer')} onClick={onClose}><X size={22} aria-hidden /></button>
      <div className="session-viewer-caption">
        <h2 ref={heading} id={title} tabIndex={-1}>{video.filename}</h2>
        {navigation && <p>{t('sessionVideo.position', { current: navigation.position, total: navigation.total })}</p>}
      </div>
      {navigation && <div className="session-viewer-navigation">
        <button type="button" className="session-viewer-control" disabled={navigation.loading || !navigation.previous}
          aria-label={t('sessionVideo.previous')} onClick={navigation.previous}><ChevronLeft size={21} aria-hidden /></button>
        <button type="button" className="session-viewer-control" disabled={navigation.loading || !navigation.next}
          aria-label={t('sessionVideo.next')} aria-busy={navigation.loading || undefined} onClick={navigation.next}><ChevronRight size={21} aria-hidden /></button>
      </div>}
      {download}
    </header>
    {(batch || error) && <div className="session-viewer-status">
      {error && <p className="session-gallery-error" role="alert">{error}</p>}
      {batch && <div className="session-viewer-batch">{batch}</div>}
    </div>}
    <SessionVideoPlayer key={video.id} info={video} playUrl={playUrl} reportUrl={reportUrl} downloadFallback={downloadFallback} />
  </div>, document.body)
}
