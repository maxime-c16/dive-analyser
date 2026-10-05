import React from 'react'
import { format, parseISO } from 'date-fns'
import { BarChart3, TrendingUp } from 'lucide-react'
import i18n from '../i18n'

interface JourneyData {
  overview: {
    total_dives: number
    unique_dive_combinations: number
    days_of_training: number
    first_dive_date: string
    latest_dive_date: string
  }
  growth: {
    first_month_average: number
    last_month_average: number
    improvement: number
    trajectory: string
  }
  journey: {
    narrative: string
  }
}

interface JourneyNarrativeProps {
  data: JourneyData
}

function JourneyNarrative({ data }: JourneyNarrativeProps) {
  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      {/* Main Narrative */}
      <div className="border border-app bg-app-panel p-8">
        <div className="prose prose-invert max-w-none">
          <p className="text-lg text-app-text leading-relaxed mb-6 italic">
            {data.journey.narrative}
          </p>
        </div>
      </div>

      {/* Growth Analysis */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Performance Comparison */}
        <div className="border border-app bg-app-panel p-6">
          <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
            <TrendingUp className="text-app-accent" size={20} />
            {i18n.t('journey.performanceProgression')}
          </h3>
          <div className="space-y-4">
            <div>
              <div className="text-app-muted text-sm mb-1">{i18n.t('journey.firstMonthAvg')}</div>
              <div className="text-2xl font-bold text-app-accent">
                {data.growth.first_month_average.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-app-muted text-sm mb-1">{i18n.t('journey.latestMonthAvg')}</div>
              <div className="text-2xl font-bold text-app-accent">
                {data.growth.last_month_average.toFixed(2)}
              </div>
            </div>
            <div className="pt-2 border-t border-app">
              <div className="text-app-muted text-sm mb-1">{i18n.t('journey.totalImprovement')}</div>
              <div className={`text-2xl font-bold ${data.growth.improvement >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {data.growth.improvement > 0 ? '+' : ''}{data.growth.improvement.toFixed(2)}
              </div>
            </div>
          </div>
        </div>

        {/* Trajectory Summary */}
        <div className="border border-app bg-app-panel p-6">
          <h3 className="text-lg font-bold mb-4">{i18n.t('journey.trajectory')}</h3>
          <div className={`rounded-lg p-4 mb-4 ${
            data.growth.trajectory === 'improving' ? 'bg-green-500/10 border border-green-500/30' :
            data.growth.trajectory === 'plateauing' ? 'bg-amber-500/10 border border-amber-500/30' :
            'border border-red-500/30 bg-red-500/10'
          }`}>
            <div className={`font-bold ${
              data.growth.trajectory === 'improving' ? 'text-green-400' :
              data.growth.trajectory === 'plateauing' ? 'text-amber-400' :
              'text-red-400'
            }`}>
              {i18n.t(`analysis.trendDirection.${data.growth.trajectory}`, { defaultValue: data.growth.trajectory })}
            </div>
          </div>
        </div>
      </div>

      {/* Timeline Stats */}
      <div className="border border-app bg-app-panel p-6">
        <h3 className="text-lg font-bold mb-6">{i18n.t('journey.timeline')}</h3>
        <div className="grid md:grid-cols-3 gap-6">
          <div>
            <div className="text-app-muted text-sm mb-2">{i18n.t('journey.trainingSpan')}</div>
            <div className="text-2xl font-bold text-app-accent">
              {data.overview.days_of_training}
              <span className="text-lg text-app-muted font-normal ml-1">{i18n.t("journey.days")}</span>
            </div>
          </div>
          <div>
            <div className="text-app-muted text-sm mb-2">{i18n.t('journey.started')}</div>
            <div className="text-sm font-mono text-app-text">
              {format(parseISO(data.overview.first_dive_date), 'MMM d, yyyy')}
            </div>
          </div>
          <div>
            <div className="text-app-muted text-sm mb-2">{i18n.t('journey.latest')}</div>
            <div className="text-sm font-mono text-app-text">
              {format(parseISO(data.overview.latest_dive_date), 'MMM d, yyyy')}
            </div>
          </div>
        </div>
      </div>

      <div className="border border-app bg-app-panel-elevated p-4">
        <div className="mb-2 flex items-center gap-2 font-bold text-app-accent"><BarChart3 className="h-4 w-4" aria-hidden="true" />{i18n.t('analysis.attempts')}</div>
        <p className="text-app-text">
          <span className="font-bold text-app-accent">{data.overview.total_dives}</span> {i18n.t('analysis.attempts')} · <span className="font-bold text-app-accent">{data.overview.unique_dive_combinations}</span> {i18n.t('journey.differentDives')}
        </p>
      </div>
    </div>
  )
}

export default JourneyNarrative
