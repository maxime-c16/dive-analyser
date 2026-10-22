import { useTranslation } from 'react-i18next'
import './evaluation/evaluationHub.css'

/**
 * Shared page/section loading state: the evaluations warm-up animation
 * (three card backs bouncing on the springboard) with a contextual label.
 *
 * Use for every initial page or section load so the app never shows a bare
 * "Chargement de la page…" text line. Keep tiny inline states as text:
 * button labels while saving, video buffering spinners, "load more"
 * pagination under an existing list, refresh banners over shown data.
 */
export default function PageLoading({ message, fullscreen = false, center = false }: {
  /** Defaults to common.loadingPage so existing tests/assertions keep passing. */
  message?: string
  /** Full-viewport centering for boot/auth/route fallbacks outside the layout. */
  fullscreen?: boolean
  /** Vertical centering in the page for former min-h spinner states. */
  center?: boolean
}) {
  const { t } = useTranslation()
  const body = (
    <div className="eval-warmup" role="status">
      <span className="eval-warmup-cards" aria-hidden><i /><i /><i /></span>
      <span className="eval-warmup-board" aria-hidden />
      <p>{message ?? t('common.loadingPage')}</p>
    </div>
  )
  if (fullscreen) return <div className="flex min-h-screen items-center justify-center">{body}</div>
  if (center) return <div className="grid min-h-[60vh] place-items-center">{body}</div>
  return body
}
