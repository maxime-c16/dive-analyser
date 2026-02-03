import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface PlateauAnalysis {
  detected: boolean
  duration_weeks: number
  max_dd_achieved: number
  current_dd: number
  dd_gap: number
  confidence_description: string
  risk_level: 'low' | 'medium' | 'high'
}

interface EmotionalTrigger {
  trigger_type: string
  affected_dives: string[]
  emotion_pattern: string
  frequency: number
  recommended_action: string
}

interface ConfidenceTrend {
  slope: 'improving' | 'stable' | 'declining'
  average_score: number
  range: [number, number]
  trend_description: string
  recommendation: string
}

interface MentalBlockData {
  plateau_analysis: PlateauAnalysis
  emotional_triggers: EmotionalTrigger[]
  confidence_trends: ConfidenceTrend
  active_recovery_plans: Array<{
    id: number
    blocked_dives: string[]
    current_phase: number
    completion_percentage: number
    created_date: string
  }>
}

interface MentalBlockAnalysisProps {
  journeyId?: number
}

function MentalBlockAnalysis({ journeyId }: MentalBlockAnalysisProps) {
  const [mentalBlocks, setMentalBlocks] = useState<MentalBlockData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedTrigger, setExpandedTrigger] = useState<number | null>(null)

  useEffect(() => {
    if (journeyId) {
      fetchMentalBlocks()
    }
  }, [journeyId])

  const fetchMentalBlocks = async () => {
    if (!journeyId) return

    try {
      setLoading(true)
      const response = await api.get(`/api/v1/psychology/mental-blocks/${journeyId}`)
      setMentalBlocks(response.data.analysis)
      setError(null)
    } catch (err) {
      console.error('Error fetching mental blocks:', err)
      setError('Unable to load mental block analysis. Please try again later.')
    } finally {
      setLoading(false)
    }
  }

  if (!journeyId) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
        <p className="text-gray-400 text-sm">Journey ID not available. Unable to load mental block analysis.</p>
      </div>
    )
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-32 bg-gray-700 rounded-lg"></div>
        <div className="h-24 bg-gray-700 rounded-lg"></div>
        <div className="h-24 bg-gray-700 rounded-lg"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
        <p className="text-red-400 font-semibold">⚠️ Analysis Error</p>
        <p className="text-red-300 text-sm mt-1">{error}</p>
      </div>
    )
  }

  if (!mentalBlocks) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
        <p className="text-gray-400 text-sm">No mental block data available yet.</p>
      </div>
    )
  }

  const { plateau_analysis, emotional_triggers, confidence_trends, active_recovery_plans } = mentalBlocks

  return (
    <div className="space-y-6">
      {/* Plateau Analysis */}
      <div className={`rounded-lg p-6 border ${
        plateau_analysis.risk_level === 'high'
          ? 'bg-red-500/10 border-red-500/30'
          : plateau_analysis.risk_level === 'medium'
          ? 'bg-yellow-500/10 border-yellow-500/30'
          : 'bg-green-500/10 border-green-500/30'
      }`}>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-bold">
            {plateau_analysis.detected ? '📈 Plateau Detected' : '✅ No Plateau Detected'}
          </h3>
          <span className={`text-xs font-semibold px-3 py-1 rounded-full ${
            plateau_analysis.risk_level === 'high'
              ? 'bg-red-500/30 text-red-400'
              : plateau_analysis.risk_level === 'medium'
              ? 'bg-yellow-500/30 text-yellow-400'
              : 'bg-green-500/30 text-green-400'
          }`}>
            {plateau_analysis.risk_level.toUpperCase()} RISK
          </span>
        </div>

        {plateau_analysis.detected && (
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <div className="text-gray-400 text-sm">Duration</div>
                <div className="text-2xl font-bold text-yellow-400">
                  {plateau_analysis.duration_weeks} weeks
                </div>
              </div>
              <div>
                <div className="text-gray-400 text-sm">DD Gap</div>
                <div className="text-2xl font-bold text-orange-400">
                  {plateau_analysis.dd_gap.toFixed(1)}
                </div>
              </div>
              <div>
                <div className="text-gray-400 text-sm">Peak Achieved</div>
                <div className="text-xl font-bold text-cyan-400">
                  {plateau_analysis.max_dd_achieved.toFixed(1)}
                </div>
              </div>
              <div>
                <div className="text-gray-400 text-sm">Current Level</div>
                <div className="text-xl font-bold text-gray-300">
                  {plateau_analysis.current_dd.toFixed(1)}
                </div>
              </div>
            </div>
            <p className="text-gray-300 text-sm leading-relaxed">
              {plateau_analysis.confidence_description}
            </p>
          </div>
        )}
      </div>

      {/* Emotional Triggers */}
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
        <h3 className="text-lg font-bold mb-4">😟 Emotional Triggers</h3>
        {emotional_triggers.length === 0 ? (
          <p className="text-gray-400 text-sm">No significant emotional triggers detected.</p>
        ) : (
          <div className="space-y-3">
            {emotional_triggers.map((trigger, idx) => (
              <div
                key={idx}
                className="bg-gray-800/50 rounded-lg p-4 border border-gray-700 cursor-pointer hover:bg-gray-800 transition-colors"
                onClick={() => setExpandedTrigger(expandedTrigger === idx ? null : idx)}
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1">
                    <p className="font-semibold text-yellow-400">{trigger.trigger_type}</p>
                    <p className="text-gray-400 text-sm mt-1">{trigger.emotion_pattern}</p>
                    <div className="flex items-center gap-4 mt-2 text-xs text-gray-500">
                      <span>Frequency: {trigger.frequency}×</span>
                      <span>Dives affected: {trigger.affected_dives.length}</span>
                    </div>
                  </div>
                  <span className="text-gray-500">{expandedTrigger === idx ? '▼' : '▶'}</span>
                </div>

                {expandedTrigger === idx && (
                  <div className="mt-4 pt-4 border-t border-gray-700 space-y-2">
                    <p className="text-sm">
                      <span className="text-gray-400">Affected dives:</span>{' '}
                      <span className="font-mono text-cyan-400">{trigger.affected_dives.join(', ')}</span>
                    </p>
                    <p className="text-sm">
                      <span className="text-gray-400">Recommendation:</span>{' '}
                      <span className="text-blue-400">{trigger.recommended_action}</span>
                    </p>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Confidence Trends */}
      <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
        <h3 className="text-lg font-bold mb-4">📊 Confidence Trends (30 days)</h3>
        <div className="grid grid-cols-3 gap-4 mb-4">
          <div>
            <div className="text-gray-400 text-sm mb-1">Trend</div>
            <div className={`text-lg font-bold ${
              confidence_trends.slope === 'improving'
                ? 'text-green-400'
                : confidence_trends.slope === 'stable'
                ? 'text-blue-400'
                : 'text-red-400'
            }`}>
              {confidence_trends.slope === 'improving'
                ? '📈 Improving'
                : confidence_trends.slope === 'stable'
                ? '➡️ Stable'
                : '📉 Declining'}
            </div>
          </div>
          <div>
            <div className="text-gray-400 text-sm mb-1">Average</div>
            <div className="text-lg font-bold text-cyan-400">
              {confidence_trends.average_score.toFixed(1)}/5
            </div>
          </div>
          <div>
            <div className="text-gray-400 text-sm mb-1">Range</div>
            <div className="text-sm text-gray-300">
              {confidence_trends.range[0].toFixed(1)} - {confidence_trends.range[1].toFixed(1)}
            </div>
          </div>
        </div>
        <p className="text-gray-400 text-sm mb-3">{confidence_trends.trend_description}</p>
        <div className="bg-blue-500/10 border border-blue-500/30 rounded p-3">
          <p className="text-blue-300 text-sm">💡 {confidence_trends.recommendation}</p>
        </div>
      </div>

      {/* Active Recovery Plans */}
      {active_recovery_plans.length > 0 && (
        <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
          <h3 className="text-lg font-bold mb-4">🎯 Active Recovery Plans ({active_recovery_plans.length})</h3>
          <div className="space-y-4">
            {active_recovery_plans.map((plan) => (
              <div key={plan.id} className="bg-gray-800/50 rounded-lg p-4 border border-green-500/20">
                <div className="flex items-start justify-between mb-2">
                  <div>
                    <p className="font-semibold text-green-400">
                      Phase {plan.current_phase === 0 ? 'Complete' : plan.current_phase} of 3
                    </p>
                    <p className="text-sm text-gray-400">
                      Target dives: <span className="font-mono text-cyan-400">{plan.blocked_dives.join(', ')}</span>
                    </p>
                  </div>
                  <span className="text-sm font-semibold text-green-400">{plan.completion_percentage}%</span>
                </div>
                <div className="w-full bg-gray-700 rounded-full h-2">
                  <div
                    className="bg-gradient-to-r from-green-500 to-cyan-400 h-2 rounded-full transition-all"
                    style={{ width: `${plan.completion_percentage}%` }}
                  ></div>
                </div>
                <p className="text-xs text-gray-500 mt-2">
                  Created: {new Date(plan.created_date).toLocaleDateString()}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default MentalBlockAnalysis
