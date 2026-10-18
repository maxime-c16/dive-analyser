import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { signupClubs, type SignupClub } from '../calendar/api'

/**
 * Optional club choice at account creation. Renders nothing while the
 * calendar feature is off (the club list answers 404). Selecting a club
 * creates a self-declared plain membership only: no group, no staff role.
 */
export default function SignupClubSelect({ id, value, onChange }: {
  id: string
  value: number | null
  onChange: (clubId: number | null) => void
}) {
  const { t } = useTranslation()
  const [clubs, setClubs] = useState<SignupClub[]>([])
  useEffect(() => {
    let live = true
    signupClubs().then(rows => { if (live) setClubs(rows) })
    return () => { live = false }
  }, [])
  if (!clubs.length) return null
  return (
    <div className="mb-4">
      <label htmlFor={id} className="mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted">
        {t('register.club')} <span className="normal-case">({t('common.optional')})</span>
      </label>
      <select
        id={id}
        value={value ?? ''}
        onChange={e => onChange(e.target.value ? Number(e.target.value) : null)}
        aria-describedby={`${id}-help`}
        className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent"
      >
        <option value="">{t('register.clubNone')}</option>
        {clubs.map(club => <option key={club.id} value={club.id}>{club.name}</option>)}
      </select>
      <p id={`${id}-help`} className="mt-1 text-xs text-app-muted">{t('register.clubHelp')}</p>
    </div>
  )
}
