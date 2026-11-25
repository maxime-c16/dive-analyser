import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../../services/api'
import TechniqueAdjustments, { type AdjustmentsLook } from './TechniqueAdjustments'
import type { ScorePanel } from './CorrectionScores'

type Context = { diver_name?: string; diver_id: number; code: string; apparatus: string; height: string; position: string; sync: boolean; eligible: number }

const contextKey = ({ diver_id, code, apparatus, height, position, sync }: Context) =>
  JSON.stringify([diver_id, code, apparatus, height, position, sync])

type Props = { viewer: number; code: string; height: string | null; scores?: ScorePanel; layout?: AdjustmentsLook }

export default function TechniqueWorkspace(props: Props) {
  return <ContextPage key={JSON.stringify([props.viewer, props.code, props.height || ''])} {...props} />
}

function ContextPage({ viewer, code, height, scores, layout }: Props) {
  const { t } = useTranslation()
  const [contexts, setContexts] = useState<Context[]>([]), [selected, setSelected] = useState(''), [after, setAfter] = useState(''), [next, setNext] = useState<string | null>(null)
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading')
  useEffect(() => {
    const controller = new AbortController()
    setContexts([]); setStatus('loading'); setNext(null)
    api.get('/api/v1/technique-history/contexts', {
      params: { code, after, height: height || undefined, order: 'volume' },
      signal: controller.signal,
    }).then(({ data }) => {
      if (controller.signal.aborted) return
      setContexts(Array.isArray(data.items) ? data.items : []); setNext(data.next); setStatus('ready')
    }).catch(() => { if (!controller.signal.aborted) setStatus('error') })
    return () => controller.abort()
  }, [viewer, code, height, after])
  const candidates = contexts.filter(c => !height || c.height === height).sort((a, b) => b.eligible - a.eligible)
  // On the code page, start on the height of the latest dive: the page's trend and videos are about it too.
  const candidateDivers = new Set(candidates.map(c => c.diver_id))
  const ownAttempts = layout?.attempts.filter(attempt => attempt.diver_id != null && candidateDivers.has(attempt.diver_id)) ?? []
  const latestHeight = ownAttempts[ownAttempts.length - 1]?.height
  const current = candidates.find(c => contextKey(c) === selected) ?? candidates.find(c => c.height === latestHeight) ?? candidates[0]
  const divers = candidateDivers.size
  // Short option label; the position is added only when two contexts would otherwise read the same.
  const shortLabel = (c: Context) => `${divers > 1 ? `${c.diver_name} · ` : ''}${c.height} · ${t(c.apparatus === 'platform' ? 'technique.platform' : 'technique.springboard')}${c.sync ? ' · SYNC' : ''}`
  if (!current) return <>
    {scores && <section className="ca-panel">{scores.header}{scores.corrections
      ? <p className="ca-correction-note" role={status === 'error' ? 'alert' : 'status'}>{t(status === 'loading' ? 'technique.loadingRatings' : status === 'error' ? 'technique.unavailable' : 'codeAnalysis.noCorrections')}</p>
      : scores.content}</section>}
    {after && <button className="ca-btn" onClick={() => setAfter('')}>{t('common.back')}</button>}
    {next && <button className="ca-btn" onClick={() => setAfter(next)}>{t('technique.moreContexts')}</button>}
  </>
  const key = contextKey(current)
  const picker = (candidates.length > 1 || after || next) && <div className="th-context">
      <label>
        <span className="th-context-label">{t('technique.divesToView')}</span>
        <select value={key} onChange={e => setSelected(e.target.value)}>
          {candidates.map(c => <option key={contextKey(c)} value={contextKey(c)}>
            {layout
              ? `${shortLabel(c)}${candidates.some(other => other !== c && shortLabel(other) === shortLabel(c)) ? ` · ${c.position || '—'}` : ''}`
              : <>{c.diver_name} · {c.height} · {t(c.apparatus === 'platform' ? 'technique.platform' : 'technique.springboard')}{c.sync ? ' · SYNC' : ''}{c.position ? ` · ${c.position}` : ''} · {t('technique.sessionDiveCount', { count: c.eligible })}</>}
          </option>)}
        </select>
      </label>
      <div className="th-pagination">
        {after && <button onClick={() => setAfter('')}>{t('common.back')}</button>}
        {next && <button onClick={() => setAfter(next)}>{t('technique.moreContexts')}</button>}
      </div>
    </div>
  return <TechniqueAdjustments viewer={viewer} key={`${viewer}-${key}`} diver={current.diver_id}
    context={{ code: current.code, apparatus: current.apparatus, height: current.height, position: current.position, sync: current.sync }}
    scores={scores} contextPicker={picker} layout={layout}
    contextLabel={`${current.diver_name ?? ''} · ${current.height} · ${t(current.apparatus === 'platform' ? 'technique.platform' : 'technique.springboard')}${current.sync ? ' · SYNC' : ''}`} />
}
