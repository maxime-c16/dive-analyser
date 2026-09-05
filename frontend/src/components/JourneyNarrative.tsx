import React from 'react'
import { format, parseISO } from 'date-fns'
import { BarChart3, Timer, TrendingUp } from 'lucide-react'

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
  const getTrajectorySentence = (trajectory: string): string => {
    if (trajectory === 'improving') {
      return 'Your trajectory is upward. You are getting better.'
    } else if (trajectory === 'plateauing') {
      return 'You\'ve reached a plateau. This is where the real work begins — consolidating what you\'ve learned.'
    } else {
      return 'You\'ve been struggling. This is temporary. Every master has been here.'
    }
  }

  return (
    <div className="space-y-8 max-w-3xl mx-auto">
      {/* Main Narrative */}
      <div className="bg-gradient-to-br from-gray-800/50 to-gray-900/50 border border-gray-700 rounded-lg p-8">
        <div className="prose prose-invert max-w-none">
          <p className="text-lg text-gray-100 leading-relaxed mb-6 italic">
            {data.journey.narrative}
          </p>
        </div>
      </div>

      {/* Growth Analysis */}
      <div className="grid md:grid-cols-2 gap-6">
        {/* Performance Comparison */}
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-6">
          <h3 className="text-lg font-bold mb-4 flex items-center gap-2">
            <TrendingUp className="text-cyan-400" size={20} />
            Performance Progression
          </h3>
          <div className="space-y-4">
            <div>
              <div className="text-gray-400 text-sm mb-1">First Month Average</div>
              <div className="text-2xl font-bold text-amber-400">
                {data.growth.first_month_average.toFixed(2)}
              </div>
            </div>
            <div>
              <div className="text-gray-400 text-sm mb-1">Latest Month Average</div>
              <div className="text-2xl font-bold text-green-400">
                {data.growth.last_month_average.toFixed(2)}
              </div>
            </div>
            <div className="pt-2 border-t border-gray-700">
              <div className="text-gray-400 text-sm mb-1">Total Improvement</div>
              <div className={`text-2xl font-bold ${data.growth.improvement >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                {data.growth.improvement > 0 ? '+' : ''}{data.growth.improvement.toFixed(2)}
              </div>
            </div>
          </div>
        </div>

        {/* Trajectory Summary */}
        <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-6">
          <h3 className="text-lg font-bold mb-4">Your Current Trajectory</h3>
          <div className={`rounded-lg p-4 mb-4 ${
            data.growth.trajectory === 'improving' ? 'bg-green-500/10 border border-green-500/30' :
            data.growth.trajectory === 'plateauing' ? 'bg-amber-500/10 border border-amber-500/30' :
            'bg-red-500/10 border border-red-500/30'
          }`}>
            <div className={`font-bold mb-2 ${
              data.growth.trajectory === 'improving' ? 'text-green-400' :
              data.growth.trajectory === 'plateauing' ? 'text-amber-400' :
              'text-red-400'
            }`}>
              {data.growth.trajectory.charAt(0).toUpperCase() + data.growth.trajectory.slice(1)}
            </div>
            <p className="text-gray-200 text-sm">
              {getTrajectorySentence(data.growth.trajectory)}
            </p>
          </div>
        </div>
      </div>

      {/* Timeline Stats */}
      <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-6">
        <h3 className="text-lg font-bold mb-6">Your Journey Timeline</h3>
        <div className="grid md:grid-cols-3 gap-6">
          <div>
            <div className="text-gray-400 text-sm mb-2">Training Span</div>
            <div className="text-2xl font-bold text-cyan-400">
              {data.overview.days_of_training}
              <span className="text-lg text-gray-400 font-normal ml-1">days</span>
            </div>
          </div>
          <div>
            <div className="text-gray-400 text-sm mb-2">Started</div>
            <div className="text-sm font-mono text-gray-300">
              {format(parseISO(data.overview.first_dive_date), 'MMM d, yyyy')}
            </div>
          </div>
          <div>
            <div className="text-gray-400 text-sm mb-2">Latest</div>
            <div className="text-sm font-mono text-gray-300">
              {format(parseISO(data.overview.latest_dive_date), 'MMM d, yyyy')}
            </div>
          </div>
        </div>
      </div>

      {/* Insight Cards */}
      <div className="grid md:grid-cols-2 gap-4">
        <div className="bg-blue-500/5 border border-blue-500/20 rounded-lg p-4">
          <div className="mb-2 flex items-center gap-2 font-bold text-blue-400"><BarChart3 className="h-4 w-4" aria-hidden="true" />Total Attempts</div>
          <p className="text-gray-300">
            You've completed <span className="font-bold text-cyan-400">{data.overview.total_dives}</span> total dive attempts across <span className="font-bold text-cyan-400">{data.overview.unique_dive_combinations}</span> different dives.
          </p>
        </div>

        <div className="bg-amber-500/5 border border-amber-500/20 rounded-lg p-4">
          <div className="mb-2 flex items-center gap-2 font-bold text-amber-400"><Timer className="h-4 w-4" aria-hidden="true" />Training Duration</div>
          <p className="text-gray-300">
            You've been training for <span className="font-bold text-cyan-400">{Math.floor(data.overview.days_of_training / 30)} months</span> and <span className="font-bold text-cyan-400">{data.overview.days_of_training % 30} days</span>.
          </p>
        </div>
      </div>

      {/* Closing Thought */}
      <div className="bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border border-cyan-500/30 rounded-lg p-6 text-center">
        <p className="text-gray-200 italic">
          "Every expert was once a beginner. You're building something that lasts — skill, confidence, and the character forged in the attempt."
        </p>
      </div>
    </div>
  )
}

export default JourneyNarrative
