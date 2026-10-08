import { useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { useTranslation } from 'react-i18next'
import { saveProfile, uploadAvatar, removeAvatar, type MemberIdentity } from '../services/communityApi'

export default function ProfileEditor({ profile, onChange, onClose }: {
  profile: MemberIdentity; onChange: (identity: MemberIdentity) => void; onClose: () => void
}) {
  const { t } = useTranslation()
  const { refresh } = useAuth()
  const [name, setName] = useState(profile.display_name)
  const [handle, setHandle] = useState(profile.handle ?? '')
  const [bio, setBio] = useState(profile.bio ?? '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const inputClass = 'mt-1 w-full border border-app bg-app px-3 py-2 text-app-text'

  async function avatar(file?: File) {
    setError(''); setBusy(true)
    try {
      if (file) onChange(await uploadAvatar(file))
      else { await removeAvatar(); onChange({ ...profile, avatar_url: null }) }
    } catch (err) {
      const status = (err as { status?: number }).status
      setError(t(status === 413 || status === 422 ? 'community.avatarInvalid' : 'community.saveError'))
    } finally { setBusy(false) }
  }

  return <form aria-label={t('community.edit')} className="mb-6 space-y-4 border border-app bg-app-panel p-4 sm:p-6" onSubmit={async event => {
    event.preventDefault(); setError(''); setBusy(true)
    try { onChange(await saveProfile({ display_name: name, handle: handle || null, bio })); onClose(); void refresh() }
    catch (err) { setError(t((err as { status?: number }).status === 409 ? 'community.handleTaken' : 'community.saveError')) }
    finally { setBusy(false) }
  }}>
    <fieldset disabled={busy} className="space-y-4">
      <label className="block text-sm text-app-muted">{t('community.name')}<input autoFocus required maxLength={120} value={name} onChange={event => setName(event.target.value)} className={inputClass} /></label>
      <label className="block text-sm text-app-muted">{t('community.handle')}<input aria-label={t('community.handle')} minLength={3} maxLength={30} pattern="[a-zA-Z0-9_]{3,30}" value={handle} onChange={event => setHandle(event.target.value)} className={inputClass} aria-describedby="handle-hint" autoCapitalize="none" autoCorrect="off" spellCheck={false} /><span id="handle-hint" className="mt-1 block text-xs">{t('community.handleHint')}</span></label>
      <label className="block text-sm text-app-muted">{t('community.bio')}<textarea aria-label={t('community.bio')} rows={3} maxLength={500} value={bio} onChange={event => setBio(event.target.value)} className={inputClass} /><span className="block text-right text-xs">{bio.length}/500</span></label>
      <div className="flex flex-wrap items-center gap-3">
        <label className="block text-sm text-app-muted">{t('community.avatar')}<input type="file" accept="image/jpeg,image/png,image/webp" className="mt-2 block w-full text-xs" onChange={event => { const file = event.target.files?.[0]; if (file) void avatar(file); event.target.value = '' }} /><span className="mt-1 block text-xs">{t('community.avatarHint')}</span></label>
        {profile.avatar_url && <button type="button" onClick={() => void avatar()} className="touch-target border border-app px-3 text-sm text-app-muted">{t('community.removeAvatar')}</button>}
      </div>
      <div className="flex gap-3"><button type="submit" className="touch-target border border-app-accent bg-app-panel-elevated px-4 text-app-accent">{busy ? t('common.loading') : t('common.save')}</button><button type="button" onClick={onClose} className="touch-target border border-app px-4 text-app-muted">{t('common.cancel')}</button></div>
    </fieldset>
    {error && <p role="alert" className="text-sm text-red-400">{error}</p>}
  </form>
}
