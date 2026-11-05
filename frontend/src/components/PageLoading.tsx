import { useTranslation } from 'react-i18next'
import './evaluation/evaluationHub.css'

/** Neutral page/section loading state with a contextual label. */
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
      <p>{message ?? t('common.loadingPage')}</p>
    </div>
  )
  if (fullscreen) return <div className="flex min-h-screen items-center justify-center">{body}</div>
  if (center) return <div className="grid min-h-[60vh] place-items-center">{body}</div>
  return body
}
