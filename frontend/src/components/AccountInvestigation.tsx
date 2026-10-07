import { useState } from 'react'
import { Copy, HelpCircle, Search } from 'lucide-react'
import { checkAccountAccess, type AccountAccessCheck } from '../services/adminUsersApi'
export default function AccountInvestigation({ accountId }: { accountId: number }) {
  const [dive, setDive] = useState('')
  const [result, setResult] = useState<AccountAccessCheck | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [summary, setSummary] = useState('')
  async function investigate() {
    setLoading(true); setError(''); setResult(null); setSummary('')
    try { setResult(await checkAccountAccess(accountId, Number(dive))) } catch (reason) { setError(reason instanceof Error ? reason.message : 'Unable to check access') } finally { setLoading(false) }
  }
  async function copySummary() {
    if (!result) return
    const text = `Account #${result.user_id} · Dive #${result.dive_id}\nViewing: ${result.can_view ? 'Allowed' : 'Denied'}\nManagement: ${result.can_manage ? 'Allowed' : 'Denied'}\n${result.explanation}\nChecked: ${result.checked_at}\n${result.scope}`
    try { await navigator.clipboard.writeText(text); setSummary('Support summary copied.') } catch { setSummary(text) }
  }
  return <article className="account-panel"><div className="account-panel-heading"><HelpCircle size={18}/><h2>Access investigator</h2></div><p className="account-muted">Check this account’s effective viewing and management permissions for a dive. This read-only check uses the application’s authorization policy.</p><form onSubmit={event => { event.preventDefault(); void investigate() }}><label className="account-search">Dive ID<input type="number" min={1} step={1} required disabled={loading} value={dive} onChange={event => { setDive(event.target.value); setResult(null); setSummary('') }} placeholder="Enter the dive ID to investigate" /></label><button className="account-button primary" disabled={loading}><Search size={14}/>{loading ? 'Checking…' : 'Run access check'}</button></form>{error && <p role="alert" className="account-alert">{error}</p>}{result && <div className="account-investigation-result"><div className="account-metrics"><div><span>Viewing</span><strong>{result.can_view ? 'Allowed' : 'Denied'}</strong></div><div><span>Management</span><strong>{result.can_manage ? 'Allowed' : 'Denied'}</strong></div></div><p>{result.explanation}</p><dl className="account-facts"><div><dt>Diver</dt><dd>{result.diver_id === null ? 'Unassigned' : `#${result.diver_id}`}</dd></div><div><dt>Visibility</dt><dd>{result.visibility}</dd></div><div><dt>Video authorization</dt><dd>{result.video_authorized === null ? 'No video attached' : result.video_authorized ? 'Allowed' : 'Denied'}</dd></div><div><dt>Checked at</dt><dd>{new Date(result.checked_at).toLocaleString()}</dd></div></dl><p className="account-muted">{result.scope}</p><button className="account-button" onClick={() => void copySummary()}><Copy size={14}/>Copy support summary</button></div>}{summary && <p role="status" className="account-muted" style={{ whiteSpace: 'pre-wrap' }}>{summary}</p>}</article>
}
