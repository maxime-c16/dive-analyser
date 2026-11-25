import { useId, useRef, type RefObject } from 'react'
import { createPortal } from 'react-dom'
import { X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { useModalOverlay } from '../../utils/overlays'
import '../clip-viewer/clipViewer.css'

type Props = {
  opener: RefObject<HTMLElement>
  onClose: () => void
  onLogin: () => void
  onSignup: () => void
}

export default function SessionDownloadAccess({ opener, onClose, onLogin, onSignup }: Props) {
  const { t } = useTranslation()
  const title = useId()
  const panel = useRef<HTMLDivElement>(null)
  const backdrop = useRef<HTMLDivElement>(null)
  const login = useRef<HTMLButtonElement>(null)
  useModalOverlay(panel, {
    layer: 70, extraRef: backdrop, onClose,
    initialFocus: () => login.current, returnFocus: () => opener.current,
  })

  return createPortal(<div ref={backdrop} className="clip-share-backdrop"
    onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <div ref={panel} className="clip-share-sheet session-access" role="dialog" aria-modal="true" aria-labelledby={title} tabIndex={-1}>
      <header className="clip-share-sheet-heading">
        <h2 id={title}>{t('sessionVideo.downloadAccessTitle')}</h2>
        <button type="button" className="clip-share-close" aria-label={t('sessionVideo.cancel')} onClick={onClose}><X size={20} aria-hidden /></button>
      </header>
      <p className="clip-share-dm-hint">{t('sessionVideo.downloadAccessHint')}</p>
      <button type="button" ref={login} className="session-access-login" onClick={onLogin}>{t('sessionVideo.signIn')}</button>
      <button type="button" className="session-access-signup" onClick={onSignup}>{t('sessionVideo.createAccount')}</button>
    </div>
  </div>, document.body)
}
