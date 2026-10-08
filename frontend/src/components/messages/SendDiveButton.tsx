import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Send, X } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import MemberPicker from './MemberPicker'
import { sendMessage, startConversation } from '../../services/messagesApi'
export default function SendDiveButton({ diveId, inline = false }: { diveId: number; inline?: boolean }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const [sent, setSent] = useState<number | null>(null)
  const keys = useRef(new Map<number, string>())
  const trigger = useRef<HTMLButtonElement>(null)
  return <div className={inline ? "direct-send-inline" : "contents"}>
    <button type="button" ref={trigger} className={inline ? "touch-target flex items-center gap-2 border border-app px-3 py-2 text-app-text" : undefined} aria-label={t('messages.sendDive')} aria-expanded={open} onClick={() => { setOpen(v => !v); setError(false); setSent(null) }}><Send size={25} /><span>{t('messages.send')}</span></button>
    {open && <div className={`clip-direct-send ${inline ? "direct-send-inline-menu" : ""}`} role="group" aria-label={t('messages.sendDive')} onKeyDown={e => { if (e.key === 'Escape') { e.stopPropagation(); setOpen(false); trigger.current?.focus() } }}>
      <div className="mb-3 flex items-center justify-between"><strong>{t('messages.sendDive')}</strong><button type="button" aria-label={t('common.close')} onClick={() => { setOpen(false); trigger.current?.focus() }}><X size={18} /></button></div>
      {sent ? <p role="status">{t('messages.diveSent')} <Link to={`/messages/${sent}`} className="underline">{t('messages.open')}</Link></p> : <MemberPicker disabled={busy} onSelect={async member => {
        if (busy) return
        setBusy(true); setError(false)
        if (!keys.current.has(member.user_id)) keys.current.set(member.user_id, crypto.randomUUID())
        try { const c = await startConversation(member.user_id); await sendMessage(c.id, { client_id: keys.current.get(member.user_id)!, dive_id: diveId }); setSent(c.id); keys.current.delete(member.user_id) }
        catch { setError(true) } finally { setBusy(false) }
      }} />}
      {error && <p role="alert" className="mt-3 text-sm">{t('messages.sendDiveError')}</p>}
    </div>}
  </div>
}
