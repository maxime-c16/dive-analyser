// Development-only synthetic data for the real club administration component.
if (!import.meta.env.DEV) throw new Error('Development fixture only')
const club = { id: 1, name: 'KCPM Montreuil', slug: 'kcpm', short_name: 'KCPM', timezone: 'Europe/Paris', self_join_enabled: true }
const groups = [{ id: 1, club_id: 1, slug: 'groupe-a', name: 'Débutants' }, { id: 2, club_id: 1, slug: 'groupe-b', name: 'Confirmés' }]
const members = ['Alex Martin', 'Camille Dubois', 'Léa Bernard'].map((display_name, i) => ({ display_name, email: `demonstration-${i + 1}@example.test`, membership: { id: i + 1, user_id: i + 1, role: i === 0 ? 'manager' : i === 1 ? 'coach' : 'member', can_publish: i < 2, can_assign_groups: i < 2 }, assignment: i === 2 ? { group_id: 1, effective_from: '2026-09-01' } : null }))
Object.assign(window, { clubsReviewFetch: async (url: string, init?: RequestInit) => {
 if (init?.method && init.method !== 'GET') return Response.json({ saved: true })
 if (/\/1\/candidates/.test(url)) return Response.json({ items: [{ user_id: 4, display_name: 'Morgan Petit', email: 'demonstration-4@example.test' }] })
 if (/\/1\/imports/.test(url)) return Response.json({ items: [] })
 if (/\/1(?:\?|$)/.test(url)) return Response.json({ club, groups, members, next_cursor: null, calendar_enabled: false, readiness: { managers: 1, groups: 2, unassigned_members: 0, occurrences: 116, scheduled_checks: 0, last_check_at: null, worker_ready: false, problems: ['scheduled_checks_missing'] } })
 return Response.json({ items: [club], next_cursor: null, calendar_enabled: false })
} })
export {}
