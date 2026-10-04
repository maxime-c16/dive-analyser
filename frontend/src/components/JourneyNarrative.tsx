import React from 'react'
import { format, parseISO } from 'date-fns'
import { BarChart3, TrendingUp } from 'lucide-react'

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
            Performance Progression
          </h3>
          <div className="space-y-4">
            <div>
              <div className="text-app-muted text-sm mb-1">First Month Average</div>
              <div className="text-2xl font-bold text-app-accent">
                {data.growth.first_month_average.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-app-muted text-sm mb-1">Latest Month Average</div>
              <div className="text-2xl font-bold text-app-accent">
                {data.growth.last_month_average.toFixed(2)}
              </div>
            </div>
            <div className="pt-2 border-t border-app">
              <div className="text-app-muted text-sm mb-1">Total Improvement</div>
              <div className={`text-2xl font-bold ${data.growth.improvement >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {data.growth.improvement > 0 ? '+' : ''}{data.growth.improvement.toFixed(2)}
              </div>
            </div>
          </div>
        </div>

        {/* Trajectory Summary */}
        <div className="border border-app bg-app-panel p-6">
          <h3 className="text-lg font-bold mb-4">Trajectory</h3>
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
              {data.growth.trajectory.charAt(0).toUpperCase() + data.growth.trajectory.slice(1)}
            </div>
          </div>
        </div>
      </div>

      {/* Timeline Stats */}
      <div className="border border-app bg-app-panel p-6">
        <h3 className="text-lg font-bold mb-6">Timeline</h3>
        <div className="grid md:grid-cols-3 gap-6">
          <div>
            <div className="text-app-muted text-sm mb-2">Training Span</div>
            <div className="text-2xl font-bold text-app-accent">
              {data.overview.days_of_training}
              <span className="text-lg text-app-muted font-normal ml-1">days</span>
            </div>
          </div>
          <div>
            <div className="text-app-muted text-sm mb-2">Started</div>
            <div className="text-sm font-mono text-app-text">
              {format(parseISO(data.overview.first_dive_date), 'MMM d, yyyy')}
            </div>
          </div>
          <div>
            <div className="text-app-muted text-sm mb-2">Latest</div>
            <div className="text-sm font-mono text-app-text">
              {format(parseISO(data.overview.latest_dive_date), 'MMM d, yyyy')}
            </div>
          </div>
        </div>
      </div>

      <div className="border border-app bg-app-panel-elevated p-4">
        <div className="mb-2 flex items-center gap-2 font-bold text-app-accent"><BarChart3 className="h-4 w-4" aria-hidden="true" />Total Attempts</div>
        <p className="text-app-text">
          <span className="font-bold text-app-accent">{data.overview.total_dives}</span> attempts · <span className="font-bold text-app-accent">{data.overview.unique_dive_combinations}</span> different dives
        </p>
      </div>
    </div>
  )
}

export default JourneyNarrative
