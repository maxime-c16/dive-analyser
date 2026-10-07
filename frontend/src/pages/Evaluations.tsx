/**
 * Évaluations space (issue #68): jury entry (a session of dives to judge)
 * and the personal spaces (owned requests / own judgements). The page is a
 * tab switch — the session view is mounted/unmounted so leaving a session
 * clears its draft and evaluation-scope media references.
 */
import { lazy, Suspense, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useAuth } from '../contexts/AuthContext'
import { OwnedRequests, MyJudgements } from '../components/evaluation/EvaluationSpaces'
import '../components/evaluation/evaluations.css'
import AutomaticScores from '../components/evaluation/AutomaticScores'

const JurySession = lazy(() => import('../components/evaluation/JurySession'))

type Tab = 'automatic' | 'community' | 'jury' | 'mine' | 'judgements'

export default function Evaluations() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const [tab, setTab] = useState<Tab>('automatic')
  const [judging, setJudging] = useState(false)

  useEffect(() => {
    document.title = `${t('evaluations.title')} · Dive Analyser`
    return () => {
      document.title = 'Dive Analyser'
    }
  }, [t])

  return (
    <div className="evaluations-page" data-judging={judging ? 'true' : undefined}>
      <header className="evaluations-header">
        <h1>{t('evaluations.title')}</h1>
        <p className="evaluations-lede">{t('evaluations.lede')}</p>
      </header>
      <nav className="evaluations-tabs" aria-label={t('evaluations.tabsAria')}>
        {tabs.map(({ key, label }) => (
          <button
            key={key}
            type="button"
            aria-current={tab === key ? 'true' : undefined}
            onClick={() => setTab(key)}
          >
            {t(label)}
          </button>
        ))}
      </nav>
      <main className="evaluations-body">
        {tab === 'automatic' && <Suspense fallback={<p role="status">{t('common.loading')}</p>}><JurySession key="automatic" automatic onStageChange={setJudging} /></Suspense>}
        {tab === 'community' && <AutomaticScores />}
        {tab === 'jury' && (
          <Suspense fallback={<p className="eval-status" role="status">{t('common.loading')}</p>}>
            <JurySession key="manual" onStageChange={setJudging} />
          </Suspense>
        )}
        {tab === 'mine' && <OwnedRequests />}
        {tab === 'judgements' && <MyJudgements />}
      </main>
      <footer className="evaluations-footer">
        <p>{t(tab === 'automatic' || tab === 'community' ? 'evaluations.automaticFooter' : 'evaluations.footerHint')}</p>
        <Link to="/dives">{t('evaluations.backToLibrary')}</Link>
      </footer>
      {!user && <p className="eval-error" role="alert">{t('evaluations.signInNeeded')}</p>}
    </div>
  )
}

const tabs: Array<{ key: Tab; label: string }> = [
  { key: 'automatic', label: 'evaluations.tabAutomatic' },
  { key: 'community', label: 'evaluations.tabCommunity' },
  { key: 'jury', label: 'evaluations.tabJury' },
  { key: 'mine', label: 'evaluations.tabMine' },
  { key: 'judgements', label: 'evaluations.tabJudgements' },
]
