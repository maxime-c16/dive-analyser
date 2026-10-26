import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { MessageSquare } from 'lucide-react'
import { startConversation } from '../../services/messagesApi'
export default function ProfileMessageButton({ userId, className }: { userId: number; className?: string }) {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  return <div><button className={className ?? "touch-target inline-flex items-center justify-center gap-2 whitespace-nowrap border border-app-accent bg-app-accent px-4 text-sm font-semibold text-black hover:bg-app-accent/90 disabled:opacity-60"} disabled={busy} onClick={async () => {
    setBusy(true); setError(false)
    try { const c = await startConversation(userId); navigate(`/messages/${c.id}`) }
    catch { setError(true) } finally { setBusy(false) }
  }}><MessageSquare className="h-4 w-4" aria-hidden />{t('messages.message')}</button>{error && <p role="alert" className="text-sm text-red-400">{t('messages.error')}</p>}</div>
}
