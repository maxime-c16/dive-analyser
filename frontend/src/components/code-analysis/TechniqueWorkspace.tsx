import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import TechniqueHistory from './TechniqueHistory'

type Context = { diver_name?: string; diver_id: number; code: string; apparatus: string; height: string; position: string; sync: boolean; eligible: number }
export default function TechniqueWorkspace({ viewer, code, height, onSelected }: { viewer: number; code: string; height: string | null; onSelected: (active: boolean) => void }) {
  const { t } = useTranslation()
  const [contexts, setContexts] = useState<Context[]>([]), [selected, setSelected] = useState(''), [after, setAfter] = useState(''), [next, setNext] = useState<string | null>(null)
  useEffect(() => { setAfter(''); setSelected(''); setContexts([]) }, [viewer, code])
  useEffect(() => {
    let current = true
    setContexts([])
    api.get('/api/v1/technique-history/contexts', { params: { code, after } }).then(({ data }) => { if (current) { setContexts(Array.isArray(data.items) ? data.items : []); setNext(data.next) } }).catch(() => { if (current) setContexts([]) })
    return () => { current = false }
  }, [viewer, code, after])
  const candidates = contexts.filter(c => !height || c.height === height)
  const current = candidates.find(c => JSON.stringify(c) === selected) ?? candidates[0]
  if (!current) return next ? <button className="ca-btn" onClick={() => setAfter(next)}>{t('technique.context')}</button> : null
  const key = JSON.stringify(current)
  return <div>
    {(candidates.length > 1 || after || next) && <div className="th-context"><label><span className="th-context-label">{t('technique.divesToView')}</span><select value={key} onChange={e => setSelected(e.target.value)}>{candidates.map(c => <option key={JSON.stringify(c)} value={JSON.stringify(c)}>{c.diver_name} · {c.height} · {t(c.apparatus === 'platform' ? 'technique.platform' : 'technique.springboard')}{c.sync ? ' · SYNC' : ''}{c.position ? ` · ${c.position}` : ''}</option>)}</select></label><div className="th-pagination">{after && <button onClick={() => setAfter('')}>{t('common.back')}</button>}{next && <button onClick={() => setAfter(next)}>{t('technique.moreContexts')}</button>}</div></div>}
    <TechniqueHistory key={`${viewer}-${key}`} diver={current.diver_id} context={{ code: current.code, apparatus: current.apparatus, height: current.height, position: current.position, sync: current.sync }} onSelected={onSelected} />
  </div>
}
