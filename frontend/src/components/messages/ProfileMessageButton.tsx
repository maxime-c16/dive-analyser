import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { startConversation } from '../../services/messagesApi'
export default function ProfileMessageButton({ userId }: { userId: number }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  return <div><button className="touch-target border border-app px-3 text-sm text-app-text" disabled={busy} onClick={async () => {
    setBusy(true); setError(false)
    try { const c = await startConversation(userId); navigate(`/messages/${c.id}`) }
    catch { setError(true) } finally { setBusy(false) }
  }}>{t('messages.message')}</button>{error && <p role="alert" className="text-sm text-red-400">{t('messages.error')}</p>}</div>
}
