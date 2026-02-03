import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface RecoveryPhase {
  phase_number: number
  duration_days: number
  focus: string
  activities: string[]
  success_criteria: string[]
  estimated_completion: string
}

interface RecoveryPlan {
  id: number
  journey_id: number
  blocked_dives: string[]
  created_date: string
  current_phase: number
  completion_percentage: number
  phases: RecoveryPhase[]
  recommendations: string[]
  daily_actions: string[]
  estimated_completion_date: string
}

interface RecoveryPlanDisplayProps {
  journeyId?: number
  planId?: number
  onPlanUpdate?: (planId: number, phase: number, percentage: number) => void
}

function RecoveryPlanDisplay({ journeyId, planId, onPlanUpdate }: RecoveryPlanDisplayProps) {
  const [plan, setPlan] = useState<RecoveryPlan | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedPhase, setExpandedPhase] = useState<number>(1)
  const [updatingPhase, setUpdatingPhase] = useState(false)

  useEffect(() => {
    if (planId) {
      fetchRecoveryPlan()
    }
  }, [planId])

  const fetchRecoveryPlan = async () => {
    if (!planId || !journeyId) return

    try {
      setLoading(true)
      const response = await api.get(`/api/v1/psychology/recovery-plans/${journeyId}`)
      // Find the specific plan
      const plans = response.data.plans || []
      const foundPlan = plans.find((p: RecoveryPlan) => p.id === planId)
      if (foundPlan) {
        setPlan(foundPlan)
      } else {
        setError('Recovery plan not found.')
      }
      setError(null)
    } catch (err) {
      console.error('Error fetching recovery plan:', err)
      setError('Unable to load recovery plan. Please try again later.')
    } finally {
      setLoading(false)
    }
  }

  const handlePhaseUpdate = async (newPhase: number, percentage: number) => {
    if (!plan) return

    try {
      setUpdatingPhase(true)
      await api.put(`/api/v1/psychology/recovery-plan/${plan.id}`, null, {
        params: {
          current_phase: newPhase,
          completion_percentage: percentage,
        },
      })

      if (onPlanUpdate) {
        onPlanUpdate(plan.id, newPhase, percentage)
      }

      // Refresh plan
      fetchRecoveryPlan()
    } catch (err) {
      console.error('Error updating recovery plan:', err)
      alert('Failed to update recovery plan. Please try again.')
    } finally {
      setUpdatingPhase(false)
    }
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        <div className="h-48 bg-gray-700 rounded-lg"></div>
        <div className="h-32 bg-gray-700 rounded-lg"></div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
        <p className="text-red-400 font-semibold">⚠️ Error</p>
        <p className="text-red-300 text-sm mt-1">{error}</p>
      </div>
    )
  }

  if (!plan) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
        <p className="text-gray-400 text-sm">No recovery plan available.</p>
      </div>
    )
  }

  const currentPhase = plan.phases.find((p) => p.phase_number === plan.current_phase)

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="bg-gradient-to-r from-cyan-600/10 to-blue-600/10 rounded-lg p-6 border border-cyan-500/20">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h2 className="text-2xl font-bold mb-2">🎯 Mental Block Recovery Plan</h2>
            <p className="text-gray-400">
              Systematic 3-phase approach to overcome mental blocks and rebuild confidence
            </p>
          </div>
          <span className="text-4xl font-bold text-cyan-400">{plan.completion_percentage}%</span>
        </div>

        <div className="space-y-2">
          <p className="text-sm text-gray-300">
            <span className="text-gray-500">Target dives:</span>{' '}
            <span className="font-mono text-yellow-400 font-semibold">{plan.blocked_dives.join(', ')}</span>
          </p>
          <p className="text-sm text-gray-300">
            <span className="text-gray-500">Estimated completion:</span>{' '}
            <span className="text-cyan-400">{new Date(plan.estimated_completion_date).toLocaleDateString()}</span>
          </p>
        </div>

        {/* Progress Bar */}
        <div className="mt-4">
          <div className="w-full bg-gray-700 rounded-full h-3">
            <div
              className="bg-gradient-to-r from-yellow-400 via-cyan-400 to-green-400 h-3 rounded-full transition-all"
              style={{ width: `${plan.completion_percentage}%` }}
            ></div>
          </div>
        </div>
      </div>

      {/* Phases */}
      <div className="space-y-4">
        {plan.phases.map((phase) => {
          const isActive = phase.phase_number === plan.current_phase
          const isComplete = phase.phase_number < plan.current_phase
          const isExpanded = expandedPhase === phase.phase_number

          return (
            <div
              key={phase.phase_number}
              className={`rounded-lg border transition-all ${
                isActive
                  ? 'bg-green-500/10 border-green-500/30'
                  : isComplete
                  ? 'bg-blue-500/10 border-blue-500/20'
                  : 'bg-gray-800/50 border-gray-700'
              }`}
            >
              <button
                onClick={() => setExpandedPhase(isExpanded ? -1 : phase.phase_number)}
                className="w-full p-4 flex items-center justify-between hover:bg-black/20 transition-colors text-left"
              >
                <div className="flex items-center gap-4 flex-1">
                  <div
                    className={`w-10 h-10 rounded-full flex items-center justify-center font-bold text-sm ${
                      isComplete
                        ? 'bg-blue-500/30 text-blue-400'
                        : isActive
                        ? 'bg-green-500/30 text-green-400 border-2 border-green-400'
                        : 'bg-gray-600/30 text-gray-400'
                    }`}
                  >
                    {isComplete ? '✓' : phase.phase_number}
                  </div>
                  <div className="flex-1">
                    <h4 className={`font-bold ${isActive ? 'text-green-400' : isComplete ? 'text-blue-400' : 'text-gray-400'}`}>
                      Phase {phase.phase_number}: {phase.focus}
                    </h4>
                    <p className="text-sm text-gray-400 mt-1">
                      {phase.duration_days} days • {phase.success_criteria.length} success criteria
                    </p>
                  </div>
                </div>
                <span className="text-gray-500">{isExpanded ? '▼' : '▶'}</span>
              </button>

              {isExpanded && (
                <div className="px-4 pb-4 border-t border-gray-700 space-y-4">
                  {/* Activities */}
                  <div>
                    <h5 className="font-semibold text-gray-300 mb-2">📋 Activities</h5>
                    <ul className="space-y-2">
                      {phase.activities.map((activity, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm text-gray-400">
                          <span className="text-cyan-400 font-bold">•</span>
                          {activity}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Success Criteria */}
                  <div>
                    <h5 className="font-semibold text-gray-300 mb-2">✅ Success Criteria</h5>
                    <ul className="space-y-2">
                      {phase.success_criteria.map((criterion, idx) => (
                        <li key={idx} className="flex items-start gap-2 text-sm text-gray-400">
                          <input
                            type="checkbox"
                            className="mt-1 accent-green-500"
                            disabled
                          />
                          {criterion}
                        </li>
                      ))}
                    </ul>
                  </div>

                  {/* Phase Controls */}
                  {isActive && (
                    <div className="bg-black/20 rounded p-3 border border-green-500/20 space-y-3 pt-4 mt-4 border-t">
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-gray-400">Mark phase as complete:</span>
                        <button
                          onClick={() => handlePhaseUpdate(phase.phase_number + 1, Math.min(100, plan.completion_percentage + 25))}
                          disabled={updatingPhase}
                          className="px-4 py-2 bg-green-500/30 hover:bg-green-500/50 text-green-400 rounded text-sm font-semibold transition-colors disabled:opacity-50"
                        >
                          {updatingPhase ? 'Updating...' : 'Next Phase →'}
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )
        })}

        {plan.current_phase === 0 && (
          <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-6 text-center">
            <h4 className="text-2xl font-bold text-green-400 mb-2">🎉 Recovery Complete!</h4>
            <p className="text-gray-400">
              You've successfully completed your mental block recovery plan. Time to tackle new challenges!
            </p>
          </div>
        )}
      </div>

      {/* Recommendations */}
      {plan.recommendations.length > 0 && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-4">
          <h5 className="font-semibold text-blue-400 mb-2">💡 Key Recommendations</h5>
          <ul className="space-y-1 text-sm text-gray-300">
            {plan.recommendations.map((rec, idx) => (
              <li key={idx} className="flex gap-2">
                <span className="text-blue-400">→</span>
                {rec}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Daily Actions */}
      {plan.daily_actions.length > 0 && (
        <div className="bg-purple-500/10 border border-purple-500/20 rounded-lg p-4">
          <h5 className="font-semibold text-purple-400 mb-2">📅 Today's Actions</h5>
          <ul className="space-y-1 text-sm text-gray-300">
            {plan.daily_actions.map((action, idx) => (
              <li key={idx} className="flex gap-2">
                <input type="checkbox" className="accent-purple-500" />
                <span>{action}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default RecoveryPlanDisplay
