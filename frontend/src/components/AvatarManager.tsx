import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { removeAvatar, uploadAvatar, saveAvatarStyle } from '../services/communityApi'
import MemberAvatar, { AVATAR_HUDS, type AvatarIdentity } from './MemberAvatar'

type AvatarMember = AvatarIdentity & { user_id: number }

export default function AvatarManager({ member, onChange, onBusyChange }: {
  member: AvatarMember; onChange: (member: AvatarMember) => void | Promise<void>; onBusyChange?: (busy: boolean) => void
}) {
  const { t } = useTranslation()
  const [current, setCurrent] = useState(member)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState(false)
  const pending = useRef(false)
  const generation = useRef(0)
  useEffect(() => { onBusyChange?.(busy) }, [busy, onBusyChange])
  useEffect(() => { setCurrent(member) }, [member])
  useEffect(() => {
    generation.current += 1
    pending.current = false
    setBusy(false); setError(''); setSaved(false)
    return () => { generation.current += 1 }
  }, [member.user_id])

  async function mutate(action: () => Promise<AvatarMember>) {
    if (pending.current) return
    pending.current = true
    const token = generation.current
    setBusy(true); setError(''); setSaved(false)
    try {
      const next = await action()
      if (token !== generation.current) return
      setCurrent(next)
      await onChange(next)
      if (token === generation.current) setSaved(true)
    } catch (err) {
      if (token !== generation.current) return
      const status = (err as { status?: number }).status
      setError(t(status === 413 || status === 422 ? 'community.avatarInvalid' : 'community.saveError'))
    } finally {
      if (token === generation.current) { pending.current = false; setBusy(false) }
    }
  }

  return <section className="avatar-manager" aria-label={t('avatar.title')}>
    <h3>{t('avatar.title')}</h3>
    <p>{t('avatar.description')}</p>
    <div className="avatar-manager-controls">
      <MemberAvatar member={current} size={72} />
      <label className="avatar-file-button">
        {t(current.avatar_url ? 'avatar.replace' : 'avatar.upload')}
        <input type="file" aria-label={t('community.avatar')} accept="image/jpeg,image/png,image/webp" disabled={busy} onChange={event => {
          const file = event.target.files?.[0]
          event.target.value = ''
          if (!file) return
          if (file.size > 2 * 1024 * 1024 || !['image/jpeg', 'image/png', 'image/webp'].includes(file.type)) {
            setSaved(false); setError(t('community.avatarInvalid')); return
          }
          void mutate(() => uploadAvatar(file))
        }} />
      </label>
      {current.avatar_url && <button type="button" disabled={busy} onClick={() => void mutate(async () => {
        await removeAvatar()
        return { ...current, avatar_url: null }
      })}>{t('community.removeAvatar')}</button>}
    </div>
    <p>{t('community.avatarHint')}</p>
    <h3>{t('avatar.hud')}</h3>
    <div className="avatar-hud-options" role="group" aria-label={t('avatar.hud')}>
      {AVATAR_HUDS.map(hud => <button key={hud} type="button" disabled={busy} aria-pressed={(current.avatar_hud ?? 'reticle') === hud}
        onClick={() => void mutate(() => saveAvatarStyle(hud))}>
        <MemberAvatar member={current} hud={hud} size={60} />
        <span>{t(`avatar.${hud}`)}</span>
      </button>)}
    </div>
    <div aria-live="polite">{busy ? <p className="avatar-saved">{t('common.loading')}</p> : saved && <p className="avatar-saved">{t('avatar.saved')}</p>}</div>
    {error && <p role="alert" className="avatar-error">{error}</p>}
  </section>
}
