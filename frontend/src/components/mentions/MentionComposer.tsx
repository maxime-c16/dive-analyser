import { useEffect, useId, useRef, useState } from 'react'
import type { RefObject } from 'react'
import { useTranslation } from 'react-i18next'
import { searchMembers } from '../../services/communityApi'
import type { MemberIdentity } from '../../services/communityApi'
import { editMentionValue } from './mentionValue'
import type { MentionValue } from './mentionValue'
import './mentions.css'

export default function MentionComposer({ value, onChange, id, placeholder, disabled, allowMentions = true, inputRef }: {
  value: MentionValue; onChange: (value: MentionValue) => void; id: string; placeholder: string
  disabled?: boolean; allowMentions?: boolean; inputRef?: RefObject<HTMLTextAreaElement>
}) {
  const { t } = useTranslation()
  const ownRef = useRef<HTMLTextAreaElement>(null)
  const ref = inputRef ?? ownRef
  const listId = useId()
  const [cursor, setCursor] = useState(0)
  const [dismissed, setDismissed] = useState(false)
  const [items, setItems] = useState<MemberIdentity[]>([])
  const [selected, setSelected] = useState(0)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('ready')
  const [retry, setRetry] = useState(0)
  const match = value.body.slice(0, cursor).match(/(?:^|\s)@([^@\n]{0,40})$/)
  const query = match?.[1] ?? null
  const start = query === null ? 0 : cursor - query.length - 1
  const open = allowMentions && !disabled && !dismissed && query !== null && !value.mentions.some(m => start >= m.start && start < m.end)
  useEffect(() => {
    setItems([]); setSelected(0)
    if (!open || query === null) return
    const controller = new AbortController()
    setStatus('loading')
    const timer = setTimeout(() => {
      searchMembers(query, undefined, controller.signal).then(page => {
        if (!controller.signal.aborted) { setItems(page.items.slice(0, 8)); setStatus('ready') }
      }).catch(() => { if (!controller.signal.aborted) setStatus('error') })
    }, 180)
    return () => { clearTimeout(timer); controller.abort() }
  }, [open, query, retry])
  const choose = (member: MemberIdentity) => {
    const label = `@${member.handle || member.display_name}`
    const body = value.body.slice(0, start) + label + ' ' + value.body.slice(cursor)
    if (body.length > 2000 || value.mentions.length >= 10) return
    const edited = editMentionValue(value, body)
    onChange({ ...edited, mentions: [...edited.mentions, { user_id: member.user_id, start, end: start + label.length }] })
    setDismissed(true)
    requestAnimationFrame(() => { ref.current?.focus(); ref.current?.setSelectionRange(start + label.length + 1, start + label.length + 1) })
  }
  return <div className="mention-composer">
    <textarea ref={ref} id={id} placeholder={placeholder} maxLength={2000} rows={2} value={value.body} disabled={disabled}
      aria-autocomplete={allowMentions ? 'list' : undefined} aria-controls={open ? listId : undefined}
      aria-expanded={allowMentions ? open : undefined} aria-activedescendant={open && items[selected] ? `${listId}-${selected}` : undefined}
      onBlur={() => setDismissed(true)}
      onSelect={event => setCursor(event.currentTarget.selectionStart)}
      onChange={event => { onChange(editMentionValue(value, event.target.value)); setCursor(event.target.selectionStart); setDismissed(false) }}
      onKeyDown={event => {
        if (!open) return
        if (event.key === 'Escape') { event.preventDefault(); setDismissed(true) }
        if (items.length && ['ArrowDown', 'ArrowUp', 'Enter'].includes(event.key)) {
          event.preventDefault()
          if (event.key === 'Enter') choose(items[selected])
          else setSelected(i => (i + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length)
        }
      }} />
    {open && <div className="mention-menu">
      <div role="listbox" id={listId} aria-label={t('mentions.choose')}>
        {items.map((member, index) => <button type="button" role="option" id={`${listId}-${index}`} aria-selected={selected === index} key={member.user_id}
          onMouseDown={event => event.preventDefault()} onClick={() => choose(member)}>
          <strong>{member.display_name}</strong>{member.handle && <span>@{member.handle}</span>}
        </button>)}
      </div>
      {status === 'loading' && <p role="status">{t('mentions.loading')}</p>}
      {status === 'ready' && !items.length && <p role="status">{t('mentions.empty')}</p>}
      {status === 'error' && <p role="alert">{t('mentions.error')} <button type="button" onMouseDown={e => e.preventDefault()} onClick={() => setRetry(n => n + 1)}>{t('common.retry')}</button></p>}
    </div>}
  </div>
}
