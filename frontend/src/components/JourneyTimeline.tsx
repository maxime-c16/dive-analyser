import React, { useState } from 'react'
import { format, parseISO } from 'date-fns'
import { ChevronDown } from 'lucide-react'

interface Milestone {
  type: string
  dive_code: string
  height: string
  title: string
  narrative: string
  date: string
  significance: number
  // Two-phase scoring (optional)
  phase1_performance?: string
  phase2_performance?: string
  phase_insight?: string
}

interface JourneyTimelineProps {
  milestones: Milestone[]
}

const getMilestoneEmoji = (type: string): string => {
  const emojiMap: { [key: string]: string } = {
    breakthrough: '🔥',
    redemption: '✨',
    first_attempt: '👶',
    first_success: '🎯',
    first_perfect: '💎',
    comeback: '🔄',
    consistency_achieved: '⚙️',
    plateau_broken: '📈',
    avoided_dive_attempted: '🦾',
    success_streak: '🌊',
    first_from_height: '📍',
    first_good: '✅',
    perfect_streak: '💫',
    new_height_conquered: '⛰️',
    training_streak: '💪',
  }
  return emojiMap[type] || '⭐'
}

const getSignificanceColor = (significance: number): string => {
  if (significance === 5) return 'from-red-500 to-orange-500'
  if (significance === 4) return 'from-amber-500 to-orange-500'
  if (significance === 3) return 'from-yellow-500 to-amber-500'
  return 'from-blue-500 to-cyan-500'
}

const getSignificanceBorder = (significance: number): string => {
  if (significance === 5) return 'border-red-500/50'
  if (significance === 4) return 'border-amber-500/50'
  if (significance === 3) return 'border-yellow-500/50'
  return 'border-blue-500/30'
}

const MilestoneCard: React.FC<{ milestone: Milestone; index: number }> = ({ milestone, index }) => {
  const [expanded, setExpanded] = useState(false)
  const emoji = getMilestoneEmoji(milestone.type)
  const significanceColor = getSignificanceColor(milestone.significance)
  const significanceBorder = getSignificanceBorder(milestone.significance)

  const formatDiveLabel = (code: string, height: string): string => {
    return `${code}${height ? ` (${height})` : ''}`
  }

  return (
    <div
      className={`border rounded-lg overflow-hidden transition-all duration-300 ${significanceBorder} ${
        expanded ? 'bg-gray-800 border-2' : 'bg-gray-900/50 border'
      }`}
    >
      {/* Card Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full p-4 flex items-start justify-between hover:bg-gray-800/50 transition-colors"
      >
        <div className="flex items-start gap-4 flex-1">
          {/* Emoji and Number */}
          <div className="flex items-center gap-3 flex-shrink-0">
            <div className="text-2xl">{emoji}</div>
            <div className={`flex items-center justify-center w-8 h-8 rounded-full bg-gradient-to-br ${significanceColor} font-bold text-white text-sm`}>
              {milestone.significance}
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 text-left">
            <h3 className="font-bold text-lg leading-tight mb-1">{milestone.title}</h3>
            <p className="text-gray-400 text-sm mb-2">{formatDiveLabel(milestone.dive_code, milestone.height)}</p>
            <p className="text-gray-300 text-sm line-clamp-2">{milestone.narrative}</p>
          </div>
        </div>

        {/* Date and Chevron */}
        <div className="flex flex-col items-end gap-2 flex-shrink-0 ml-4">
          <span className="text-gray-400 text-sm">{format(parseISO(milestone.date), 'MMM d, yyyy')}</span>
          <ChevronDown
            size={20}
            className={`text-gray-400 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </div>
      </button>

      {/* Expanded Content */}
      {expanded && (
        <div className="border-t border-gray-700 bg-gray-900 p-4 space-y-3">
          <div>
            <h4 className="text-gray-400 text-xs uppercase tracking-wide mb-2">Full Story</h4>
            <p className="text-gray-200 leading-relaxed">{milestone.narrative}</p>
          </div>

          {/* Two-Phase Analysis */}
          {milestone.phase1_performance && milestone.phase2_performance && (
            <div className="pt-2 border-t border-gray-800">
              <h4 className="text-gray-400 text-xs uppercase tracking-wide mb-3">Two-Phase Analysis</h4>
              <div className="grid grid-cols-2 gap-3 mb-3">
                <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
                  <div className="text-gray-400 text-xs mb-1">Phase 1: Hurdle + Flight</div>
                  <div className="text-lg font-bold text-cyan-400">{milestone.phase1_performance}</div>
                </div>
                <div className="bg-gray-800/50 rounded p-3 border border-gray-700">
                  <div className="text-gray-400 text-xs mb-1">Phase 2: Opening + Entry</div>
                  <div className="text-lg font-bold text-cyan-400">{milestone.phase2_performance}</div>
                </div>
              </div>
              {milestone.phase_insight && (
                <div className="bg-blue-500/10 border border-blue-500/30 rounded p-3">
                  <p className="text-blue-300 text-sm">{milestone.phase_insight}</p>
                </div>
              )}
            </div>
          )}

          <div className="grid grid-cols-3 gap-4 pt-3 border-t border-gray-800">
            <div>
              <div className="text-gray-500 text-xs">Significance</div>
              <div className="text-lg font-bold text-amber-400">{milestone.significance}/5</div>
            </div>
            <div>
              <div className="text-gray-500 text-xs">Type</div>
              <div className="text-sm font-mono text-cyan-400">{milestone.type.replace(/_/g, ' ')}</div>
            </div>
            <div>
              <div className="text-gray-500 text-xs">Date</div>
              <div className="text-sm font-mono text-gray-300">{format(parseISO(milestone.date), 'yyyy-MM-dd')}</div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function JourneyTimeline({ milestones }: JourneyTimelineProps) {
  if (milestones.length === 0) {
    return (
      <div className="text-center py-12">
        <p className="text-gray-400 mb-2">No milestones at this significance level yet.</p>
        <p className="text-gray-500 text-sm">Keep diving. Your breakthroughs will come.</p>
      </div>
    )
  }

  // Sort by date, most recent first
  const sorted = [...milestones].sort((a, b) => new Date(b.date).getTime() - new Date(a.date).getTime())

  return (
    <div className="space-y-4">
      {/* Timeline visual line */}
      <div className="relative">
        <div className="absolute left-0 md:left-8 top-0 bottom-0 w-0.5 bg-gradient-to-b from-red-500 via-amber-500 to-blue-500 opacity-30"></div>

        <div className="space-y-4 md:pl-24">
          {sorted.map((milestone, index) => (
            <div key={`${milestone.date}-${milestone.dive_code}-${index}`} className="relative">
              {/* Timeline dot */}
              <div className={`absolute -left-10 md:-left-20 top-6 w-6 h-6 rounded-full border-4 border-gray-950 ${
                milestone.significance === 5 ? 'bg-red-500' :
                milestone.significance === 4 ? 'bg-amber-500' :
                milestone.significance === 3 ? 'bg-yellow-500' :
                'bg-blue-500'
              }`}></div>

              <MilestoneCard milestone={milestone} index={index} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export default JourneyTimeline
