import { useCallback, useEffect, useState } from 'react'
import { KeyRound, LogOut, Pencil, RefreshCw, Search, UserPlus, Users } from 'lucide-react'
import {
  bindDiver,
  createUser,
  getUser,
  listAllDivers,
  listUsers,
  resetPassword,
  revokeSessions,
  roleTitle,
  unbindDiver,
  updateUser,
  type AdminDiver,
  type AdminUser,
  type PublicRole,
} from '../services/adminUsersApi'

const inputCls =
  'w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent'
const labelCls = 'mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted'

type StatusFilter = 'all' | 'active' | 'disabled'

type Notice = { kind: 'ok' | 'error'; text: string } | null

function RoleBadge({ user }: { user: AdminUser }) {
  return (
    <span
      className={`shrink-0 border px-2 py-0.5 text-xs font-medium ${
        user.is_admin ? 'border-app text-app-muted' : 'border-app-accent text-app-accent'
      }`}
    >
      {roleTitle(user)}
    </span>
  )
}

export default function AdminUsers({ currentUserId, onManage, initialQuery = '', initialStatus = 'all', initialOffset = 0, onDirectoryChange }: { currentUserId?: number; onManage?: (id: number) => void; initialQuery?: string; initialStatus?: StatusFilter; initialOffset?: number; onDirectoryChange?: (query: string, status: StatusFilter, offset: number) => void }) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [total, setTotal] = useState(0)
  const [divers, setDivers] = useState<AdminDiver[]>([])
  const [query, setQuery] = useState(initialQuery)
  const [offset, setOffset] = useState(initialOffset)
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(initialStatus)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState<Notice>(null)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detail, setDetail] = useState<AdminUser | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [busy, setBusy] = useState(false)

  // Create form state
  const [createEmail, setCreateEmail] = useState('')
  const [createName, setCreateName] = useState('')
  const [createRole, setCreateRole] = useState<PublicRole>('diver')
  const [createPassword, setCreatePassword] = useState('')
  const [createDiverId, setCreateDiverId] = useState('')

  // Edit form state (per selected user)
  const [editName, setEditName] = useState('')
  const [editEmail, setEditEmail] = useState('')
  const [editRole, setEditRole] = useState<PublicRole>('diver')
  const [editActive, setEditActive] = useState(true)

  // Password reset state
  const [newPassword, setNewPassword] = useState('')

  const selected = users.find(u => u.user_id === selectedId) ?? null
  const isSelf = selected !== null && selected.user_id === currentUserId
  const bindings = detail?.user_id === selectedId ? (detail.diver_ids ?? []) : []
  const bindingTotal = detail?.user_id === selectedId ? (detail.diver_binding_total ?? bindings.length) : bindings.length

  const refreshDetail = useCallback(async (userId: number, signal?: AbortSignal) => {
    setDetailLoading(true)
    try {
      const loaded = await getUser(userId)
      if (!signal?.aborted) setDetail(loaded)
    } catch (reason) {
      if ((reason as Error).name !== 'AbortError' && !signal?.aborted) {
        setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : 'Unable to load user' })
      }
    } finally {
      if (!signal?.aborted) setDetailLoading(false)
    }
  }, [])

  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true)
      try {
        const [directory, diverDirectory] = await Promise.all([
          listUsers({
            q: query.trim() || undefined,
            limit: 50, offset,
            is_active: statusFilter === 'all' ? undefined : statusFilter === 'active',
          }),
          onManage ? Promise.resolve([]) : listAllDivers(),
        ])
        if (signal?.aborted) return
        setUsers(directory.users)
        setTotal(directory.total)
        if (!onManage) setDivers(diverDirectory)
      } catch (reason) {
        if ((reason as Error).name !== 'AbortError' && !signal?.aborted) {
          setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : 'Unable to load users' })
        }
      } finally {
        if (!signal?.aborted) setLoading(false)
      }
    },
    [query, statusFilter, offset, onManage],
  )

  useEffect(() => { onDirectoryChange?.(query, statusFilter, offset) }, [query, statusFilter, offset, onDirectoryChange])

  useEffect(() => {
    const controller = new AbortController()
    void refresh(controller.signal)
    return () => controller.abort()
  }, [refresh])

  useEffect(() => {
    if (selectedId === null) {
      setDetail(null)
      return
    }
    const controller = new AbortController()
    void refreshDetail(selectedId, controller.signal)
    return () => controller.abort()
  }, [selectedId, refreshDetail])

  useEffect(() => {
    if (selected) {
      setEditName(selected.display_name)
      setEditEmail(selected.email)
      setEditRole(selected.is_admin ? 'administrator' : 'diver')
      setEditActive(selected.is_active)
      setNewPassword('')
    }
  }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  async function runMutation<T>(action: () => Promise<T>, okText: (result: T) => string) {
    setBusy(true)
    setNotice(null)
    try {
      const result = await action()
      setNotice({ kind: 'ok', text: okText(result) })
      await refresh()
      if (selectedId !== null) await refreshDetail(selectedId)
      return true
    } catch (reason) {
      setNotice({ kind: 'error', text: reason instanceof Error ? reason.message : 'Action failed' })
      return false
    } finally {
      setBusy(false)
    }
  }

  const submitCreate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (createPassword.length < 10) {
      setNotice({ kind: 'error', text: 'Password must be at least 10 characters' })
      return
    }
    if (createRole === 'administrator' && !createDiverId) {
      setNotice({ kind: 'error', text: 'An administrator account needs a diver binding' })
      return
    }
    const created = await runMutation(
      () =>
        createUser({
          email: createEmail.trim(),
          display_name: createName.trim() || undefined,
          role: createRole,
          password: createPassword,
          diver_id: createDiverId ? Number(createDiverId) : undefined,
        }),
      user => `Created ${user.email} as ${roleTitle(user)}`,
    )
    if (!created) return
    setCreateEmail('')
    setCreateName('')
    setCreatePassword('')
    setCreateDiverId('')
    setCreateRole('diver')
    setShowCreate(false)
  }

  if (!selected && selectedId !== null) setSelectedId(null)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-52 flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-app-muted" aria-hidden />
          <input
            type="search"
            aria-label="Search users"
            placeholder="Search name or email…"
            value={query}
            onChange={e => {
              setQuery(e.target.value)
              setOffset(0)
              setNotice(null)
            }}
            onKeyDown={e => {
              if (e.key === 'Enter') void refresh()
            }}
            className={`${inputCls} pl-9`}
          />
        </div>
        <label className="flex items-center gap-2 text-sm text-app-muted">
          Status
          <select
            aria-label="Filter by status"
            value={statusFilter}
            onChange={e => {
              setStatusFilter(e.target.value as StatusFilter)
              setOffset(0)
              setNotice(null)
            }}
            className="border border-app bg-app-panel-elevated px-2 py-2 text-sm text-app-text"
          >
            <option value="all">All</option>
            <option value="active">Active</option>
            <option value="disabled">Disabled</option>
          </select>
        </label>
        <button
          type="button"
          onClick={() => {
            setNotice(null)
            void refresh()
          }}
          disabled={loading}
          className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-3 text-sm text-app-text disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden />
          Refresh
        </button>
        <button
          type="button"
          onClick={() => { setShowCreate(value => !value); if (onManage && !showCreate) void listAllDivers().then(setDivers).catch(reason => setNotice({ kind: 'error', text: String(reason) })) }}
          aria-expanded={showCreate}
          className="touch-target inline-flex items-center gap-2 border border-app-strong bg-app-panel px-3 text-sm font-medium text-app-text"
        >
          <UserPlus className="h-4 w-4" aria-hidden />
          New user
        </button>
      </div>

      {notice && (
        <p role={notice.kind === 'error' ? 'alert' : 'status'} className={`text-sm ${notice.kind === 'ok' ? 'text-app-accent' : 'text-red-400'}`}>
          {notice.text}
        </p>
      )}

      {showCreate && (
        <form onSubmit={submitCreate} className="space-y-4 border border-app bg-app-panel p-5">
          <h3 className="font-semibold text-app-text">Create user</h3>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className={labelCls} htmlFor="admin-create-email">Email</label>
              <input
                id="admin-create-email"
                type="email"
                value={createEmail}
                onChange={e => setCreateEmail(e.target.value)}
                className={inputCls}
                required
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="admin-create-name">Display name (optional)</label>
              <input
                id="admin-create-name"
                type="text"
                value={createName}
                onChange={e => setCreateName(e.target.value)}
                maxLength={120}
                className={inputCls}
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="admin-create-role">Role</label>
              <select
                id="admin-create-role"
                value={createRole}
                onChange={e => setCreateRole(e.target.value as PublicRole)}
                className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text"
              >
                <option value="diver">Diver — regular user</option>
                <option value="administrator">Administrator</option>
              </select>
            </div>
            <div>
              <label className={labelCls} htmlFor="admin-create-password">Password (10+ characters)</label>
              <input
                id="admin-create-password"
                type="password"
                value={createPassword}
                onChange={e => setCreatePassword(e.target.value)}
                autoComplete="new-password"
                minLength={10}
                className={inputCls}
                required
              />
            </div>
            <div className="sm:col-span-2">
              <label className={labelCls} htmlFor="admin-create-diver">
                Diver binding{createRole === 'administrator' ? ' (required for administrators)' : ' (optional)'}
              </label>
              <select
                id="admin-create-diver"
                value={createDiverId}
                onChange={e => setCreateDiverId(e.target.value)}
                className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text"
              >
                <option value="">No binding</option>
                {divers.map(d => (
                  <option key={d.diver_id} value={d.diver_id}>
                    {d.display_name} ({d.canonical_name})
                  </option>
                ))}
              </select>
            </div>
          </div>
          <button
            type="submit"
            disabled={busy}
            className="touch-target inline-flex items-center gap-2 border border-app-accent bg-app-panel px-4 py-2.5 text-sm font-semibold text-app-accent disabled:opacity-60"
          >
            <UserPlus className="h-4 w-4" aria-hidden />
            {busy ? 'Creating…' : 'Create user'}
          </button>
        </form>
      )}

      {loading && users.length === 0 ? (
        <div className="border border-app bg-app-panel p-10 text-center text-sm text-app-muted">Loading users…</div>
      ) : users.length === 0 ? (
        <div className="border border-app bg-app-panel p-10 text-center text-sm text-app-muted">
          No users match this filter.
        </div>
      ) : (
        <div className="overflow-x-auto border border-app bg-app-panel">
          <table className="w-full min-w-[640px] text-left text-sm">
            <caption className="sr-only">
              Users ({total} total)
            </caption>
            <thead>
              <tr className="border-b border-app text-xs uppercase tracking-wide text-app-muted">
                <th scope="col" className="px-4 py-3 font-medium">User</th>
                <th scope="col" className="px-4 py-3 font-medium">Role</th>
                <th scope="col" className="px-4 py-3 font-medium">Status</th>
                <th scope="col" className="px-4 py-3 font-medium">Divers</th>
                <th scope="col" className="px-4 py-3 font-medium">Sessions</th>
                <th scope="col" className="px-4 py-3 font-medium"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--app-border)]">
              {users.map(user => (
                <tr key={user.user_id} className={selectedId === user.user_id ? 'bg-app-panel-elevated' : undefined}>
                  <td className="px-4 py-3">
                    <div className="font-medium text-app-text">{user.display_name}</div>
                    <div className="text-xs text-app-muted">{user.email}</div>
                  </td>
                  <td className="px-4 py-3"><RoleBadge user={user} /></td>
                  <td className="px-4 py-3">
                    <span className={`text-xs font-medium ${user.is_active ? 'text-app-accent' : 'text-red-400'}`}>
                      {user.is_active ? 'Active' : 'Disabled'}
                    </span>
                  </td>
                  <td className="px-4 py-3 tabular-nums text-app-muted">{user.diver_count ?? '—'}</td>
                  <td className="px-4 py-3 tabular-nums text-app-muted">{user.live_sessions}</td>
                  <td className="px-4 py-3 text-right">
                    <button
                      type="button"
                      onClick={() => onManage ? onManage(user.user_id) : setSelectedId(current => (current === user.user_id ? null : user.user_id))}
                      aria-expanded={selectedId === user.user_id}
                      className="touch-target inline-flex items-center gap-1.5 border border-app px-3 text-xs font-medium text-app-text"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden />
                      {selectedId === user.user_id ? 'Close' : 'Manage'}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {total > 50 && <nav aria-label="User directory pages" className="flex items-center justify-between text-sm text-app-muted">
        <span>{offset + 1}–{Math.min(offset + users.length, total)} of {total} accounts</span>
        <div className="flex gap-2"><button className={inputCls} disabled={offset === 0 || loading} onClick={() => setOffset(Math.max(0, offset - 50))}>Previous</button><button className={inputCls} disabled={offset + 50 >= total || loading} onClick={() => setOffset(offset + 50)}>Next</button></div>
      </nav>}

      {selected && (
        <section aria-label={`Manage ${selected.email}`} className="space-y-4 border border-app bg-app-panel p-5">
          <div className="flex flex-wrap items-center gap-3">
            <h3 className="font-semibold text-app-text">{selected.display_name}</h3>
            <RoleBadge user={selected} />
            {isSelf && <span className="text-xs text-app-muted">(this is you)</span>}
          </div>

          <form
            onSubmit={e => {
              e.preventDefault()
              void runMutation(
                () =>
                  updateUser(selected.user_id, {
                    display_name: editName.trim(),
                    email: editEmail.trim(),
                    role: editRole,
                    is_active: editActive,
                  }),
                user => `Saved ${user.email}`,
              )
            }}
            className="grid gap-4 sm:grid-cols-2"
          >
            <div>
              <label className={labelCls} htmlFor="admin-edit-name">Display name</label>
              <input
                id="admin-edit-name"
                type="text"
                value={editName}
                onChange={e => setEditName(e.target.value)}
                maxLength={120}
                className={inputCls}
                required
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="admin-edit-email">Email</label>
              <input
                id="admin-edit-email"
                type="email"
                value={editEmail}
                onChange={e => setEditEmail(e.target.value)}
                className={inputCls}
                required
              />
            </div>
            <div>
              <label className={labelCls} htmlFor="admin-edit-role">Role</label>
              <select
                id="admin-edit-role"
                value={editRole}
                onChange={e => setEditRole(e.target.value as PublicRole)}
                className="w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text"
              >
                <option value="diver">Diver — regular user</option>
                <option value="administrator" disabled={isSelf && !selected.is_admin}>
                  Administrator
                </option>
              </select>
              {isSelf && <p className="mt-1 text-xs text-app-muted">You cannot remove your own administrator role.</p>}
            </div>
            <div className="flex items-end pb-1">
              <label className="flex cursor-pointer items-center gap-2 text-sm text-app-text">
                <input
                  type="checkbox"
                  checked={editActive}
                  disabled={isSelf}
                  onChange={e => setEditActive(e.target.checked)}
                  className="h-4 w-4 accent-[var(--app-accent)]"
                />
                Account active
              </label>
            </div>
            <div className="sm:col-span-2">
              <button
                type="submit"
                disabled={busy}
                className="touch-target inline-flex items-center gap-2 border border-app-strong bg-app-panel px-4 py-2.5 text-sm font-medium text-app-text disabled:opacity-60"
              >
                Save changes
              </button>
            </div>
          </form>

          {!isSelf && (
            <form
              onSubmit={e => {
                e.preventDefault()
                if (newPassword.length < 10) {
                  setNotice({ kind: 'error', text: 'Password must be at least 10 characters' })
                  return
                }
                void runMutation(
                  () => resetPassword(selected.user_id, newPassword),
                  result => `Password reset. ${result.revoked_sessions} session(s) signed out.`,
                )
                setNewPassword('')
              }}
              className="border-t border-app pt-4"
            >
              <h4 className="flex items-center gap-2 text-sm font-semibold text-app-text">
                <KeyRound className="h-4 w-4 text-app-accent" aria-hidden />
                Reset password
              </h4>
              <p className="mt-1 text-xs text-app-muted">Sets a new password and signs the user out everywhere.</p>
              <div className="mt-2 flex max-w-md gap-2">
                <input
                  type="password"
                  aria-label="New password"
                  placeholder="New password (10+ characters)"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  autoComplete="new-password"
                  minLength={10}
                  className={inputCls}
                  required
                />
                <button
                  type="submit"
                  disabled={busy}
                  className="touch-target shrink-0 border border-app bg-app-panel-elevated px-4 text-sm text-app-text disabled:opacity-60"
                >
                  Reset
                </button>
              </div>
            </form>
          )}

          <div className="border-t border-app pt-4">
            <h4 className="flex items-center gap-2 text-sm font-semibold text-app-text">
              <Users className="h-4 w-4 text-app-accent" aria-hidden />
              Diver bindings
            </h4>
            {bindings.length === 0 && editRole === 'administrator' && !detailLoading && (
              <p className="mt-1 text-xs text-amber-200">Administrators without a diver binding cannot own dives — bind one below.</p>
            )}
            {detailLoading ? (
              <p className="mt-2 text-sm text-app-muted">Loading bindings…</p>
            ) : (
            <>
            {bindingTotal > bindings.length && (
              <p className="mt-1 text-xs text-app-muted">Showing {bindings.length} of {bindingTotal} bindings.</p>
            )}
            <ul className="mt-2 space-y-1.5">
              {divers.map(d => {
                const bound = bindings.includes(d.diver_id)
                return (
                  <li key={d.diver_id} className="flex items-center justify-between gap-3 border border-app px-3 py-2 text-sm">
                    <span className="min-w-0">
                      <span className="block truncate text-app-text">{d.display_name}</span>
                      <span className="block truncate text-xs text-app-muted">{d.canonical_name}</span>
                    </span>
                    {bound ? (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void runMutation(
                            () => unbindDiver(selected.user_id, d.diver_id),
                            result => (result.noop ? `No binding to ${d.display_name} existed` : `Unbound ${d.display_name}`),
                          )
                        }
                        className="touch-target shrink-0 border border-app px-3 text-xs text-app-muted hover:text-app-text disabled:opacity-60"
                      >
                        Unbind
                      </button>
                    ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() =>
                          void runMutation(
                            () => bindDiver(selected.user_id, d.diver_id),
                            result => (result.noop ? `Already bound to ${d.display_name}` : `Bound ${d.display_name}`),
                          )
                        }
                        className="touch-target shrink-0 border border-app-accent px-3 text-xs text-app-accent disabled:opacity-60"
                      >
                        Bind
                      </button>
                    )}
                  </li>
                )
              })}
            </ul>
            </>
            )}
          </div>

          <div className="flex flex-wrap gap-2 border-t border-app pt-4">
            {!isSelf && (
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void runMutation(
                    () =>
                      updateUser(selected.user_id, {
                        is_active: !selected.is_active,
                      }),
                    user => (user.is_active ? `${user.email} enabled` : `${user.email} disabled and signed out`),
                  )
                }
                className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm text-app-text disabled:opacity-60"
              >
                {selected.is_active ? 'Disable account' : 'Enable account'}
              </button>
            )}
            <button
              type="button"
              disabled={busy}
              onClick={() =>
                void runMutation(
                  () => revokeSessions(selected.user_id),
                  result => `${result.revoked_sessions} session(s) signed out`,
                )
              }
              className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel-elevated px-4 py-2.5 text-sm text-app-text disabled:opacity-60"
            >
              <LogOut className="h-4 w-4" aria-hidden />
              Sign out everywhere
            </button>
          </div>
        </section>
      )}
    </div>
  )
}
