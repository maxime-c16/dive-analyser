import React, { useState } from 'react'
import { ChevronDown, ChevronRight, Flag } from 'lucide-react'
import { format, parseISO } from 'date-fns'
import i18n from '../i18n'
import { milestoneDisplay } from '../i18n/milestones'
import { Link } from 'react-router-dom'

interface Milestone {
  type: string
  dive_code: string
  height: string
  title: string
  narrative: string
  date: string
  significance: number
  phase1_performance?: string
  phase2_performance?: string
  phase_insight?: string
}

interface JourneyTimelineProps {
  milestones: Milestone[]
}

/**
 * Milestone timing insight and narrative text come straight from the
 * backend in English; the title/label are localized from the milestone
 * type. The label keys cover every milestone family in
 * backend/app/services/milestones.py.
 */
const MILESTONE_LABEL_KEYS: Record<string, string> = {
}
const typeLabel = (type: string) => i18n.t(`milestones.labels.${type}`, { defaultValue: type.replace(/_/g, ' ') })
const priorityLabel = (value: number) => value >= 5 ? i18n.t('milestones.majorBreakthrough') : value >= 4 ? i18n.t('milestones.notableStep') : value >= 3 ? i18n.t('milestones.meaningfulProgress') : i18n.t('milestones.recordedProgress')

function MilestoneRow({ milestone }: { milestone: Milestone }) {
  const [expanded, setExpanded] = useState(false)
  const date = parseISO(milestone.date)
  const hasPhaseData = Boolean(milestone.phase1_performance && milestone.phase2_performance)
  const display = milestoneDisplay(milestone)

  return <article className={`border-l-2 ${milestone.significance >= 4 ? 'border-app-accent' : 'border-app'} bg-app-panel`}>
    <button type="button" aria-expanded={expanded} onClick={() => setExpanded((value) => !value)} className="touch-target flex w-full items-start gap-3 p-4 text-left hover:bg-app-panel-elevated sm:items-center sm:px-5">
      <time dateTime={milestone.date} className="w-12 shrink-0 text-center sm:w-20">
        <span className="block text-lg font-semibold text-app-text">{format(date, 'd')}</span>
        <span className="block text-[11px] font-medium uppercase tracking-wide text-app-muted">{format(date, 'MMM')}</span>
      </time>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1"><h3 className="font-semibold text-app-text">{display.title}</h3><span className="text-xs text-app-muted">{typeLabel(milestone.type)}</span></div>
        <p className="mt-1 text-sm text-app-muted">{milestone.dive_code}{milestone.height ? ` · ${milestone.height}` : ''}</p>
        {!expanded && <p className="mt-2 line-clamp-2 text-sm leading-5 text-app-muted">{display.narrative}</p>}
      </div>
      <div className="flex shrink-0 items-center gap-2"><span className="hidden border border-app px-2 py-1 text-xs text-app-muted sm:inline">{milestone.significance}/5</span>{expanded ? <ChevronDown className="h-5 w-5 text-app-muted" /> : <ChevronRight className="h-5 w-5 text-app-muted" />}</div>
    </button>
    {expanded && <div className="border-t border-app px-4 pb-5 pt-4 sm:px-5">
      <p className="max-w-3xl text-sm leading-6 text-app-text">{display.narrative}</p>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs"><span className="border border-app px-2 py-1 text-app-muted">{priorityLabel(milestone.significance)} · {milestone.significance}/5</span><span className="border border-app px-2 py-1 text-app-muted">{format(date, 'd MMMM yyyy')}</span><Link to={`/dives/analysis/${milestone.dive_code}`} className="touch-target inline-flex items-center gap-1 border border-app-accent px-3 text-app-accent">{i18n.t('milestones.review')} {milestone.dive_code}<ChevronRight className="h-3.5 w-3.5" /></Link></div>
      {hasPhaseData && <div className="mt-4 grid gap-2 border-t border-app pt-4 sm:grid-cols-2"><div className="border border-app p-3"><div className="text-xs text-app-muted">{i18n.t('jargon.phaseN', { n: 1 })}</div><div className="mt-1 text-lg font-semibold text-app-text">{milestone.phase1_performance}</div></div><div className="border border-app p-3"><div className="text-xs text-app-muted">{i18n.t('jargon.phaseN', { n: 2 })}</div><div className="mt-1 text-lg font-semibold text-app-text">{milestone.phase2_performance}</div></div>{milestone.phase_insight && <p className="text-sm leading-6 text-app-muted sm:col-span-2">{milestone.phase_insight}</p>}</div>}
    </div>}
  </article>
}

function JourneyTimeline({ milestones }: JourneyTimelineProps) {
  const sorted = [...milestones].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())
  if (!sorted.length) return <div className="border border-app bg-app-panel p-8 text-center"><Flag className="mx-auto h-5 w-5 text-app-muted" /><p className="mt-3 font-medium text-app-text">{i18n.t('milestones.noMatches')}</p></div>

  const major = sorted.filter((milestone) => milestone.significance >= 4).length
  return <section aria-label={i18n.t('milestones.historyAria')}><div className="mb-4 flex flex-wrap items-center justify-between gap-3 border-b border-app pb-3"><p className="text-sm text-app-muted"><span className="font-semibold text-app-text">{sorted.length}</span> {i18n.t('milestones.count')} · {i18n.t('milestones.majorNotable', { count: major })}</p></div><div className="space-y-3">{sorted.map((milestone, index) => <MilestoneRow key={`${milestone.date}-${milestone.dive_code}-${index}`} milestone={milestone} />)}</div></section>
}

export default JourneyTimeline
