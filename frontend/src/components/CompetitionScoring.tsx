import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface JudgeScore {
  judge_number: number
  score: number
}

interface DiveScoring {
  dive_id: number
  dive_code: string
  height: string
  dd_value: number
  judge_scores: JudgeScore[]
  execution_score: number | null
  final_score: number | null
}

interface CompetitionScoringProps {
  eventId: number
  onScoreSubmitted?: (diveId: number) => void
}

function CompetitionScoring({ eventId, onScoreSubmitted }: CompetitionScoringProps) {
  const [dives, setDives] = useState<DiveScoring[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedDiveId, setSelectedDiveId] = useState<number | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [judgeCount, setJudgeCount] = useState(7)

  useEffect(() => {
    fetchEventDives()
  }, [eventId])

  const fetchEventDives = async () => {
    try {
      setLoading(true)
      const response = await api.get(`/api/v1/events/${eventId}`)
      setDives(response.data.dives || [])
      setError(null)
    } catch (err) {
      console.error('Error fetching event:', err)
      setError('Failed to load event dives')
    } finally {
      setLoading(false)
    }
  }

  const selectedDive = dives.find((d) => d.dive_id === selectedDiveId)

  const updateJudgeScore = (judgeNumber: number, score: number) => {
    if (!selectedDive) return

    const updatedDives = dives.map((d) => {
      if (d.dive_id === selectedDiveId) {
        const updatedScores = d.judge_scores.map((js) =>
          js.judge_number === judgeNumber ? { ...js, score } : js
        )

        // Add score if judge doesn't exist yet
        if (!updatedScores.find((js) => js.judge_number === judgeNumber)) {
          updatedScores.push({ judge_number: judgeNumber, score })
        }

        // Calculate execution score (drop 2 high, drop 2 low, average remaining 3)
        const sorted = updatedScores.sort((a, b) => a.score - b.score)
        let executionScore = 0

        if (sorted.length >= 7) {
          // Official FINA: remove 2 highest and 2 lowest, average 3 middle
          const middle = sorted.slice(2, sorted.length - 2)
          executionScore =
            middle.reduce((sum, js) => sum + js.score, 0) / middle.length
        } else if (sorted.length >= 3) {
          // Less than 7 judges: still remove extremes if possible
          const middle = sorted.slice(Math.max(0, sorted.length - 5), sorted.length - 1)
          executionScore =
            middle.reduce((sum, js) => sum + js.score, 0) / middle.length
        }

        return {
          ...d,
          judge_scores: updatedScores,
          execution_score: executionScore > 0 ? executionScore : null,
          final_score:
            executionScore > 0 ? Number((executionScore * d.dd_value).toFixed(2)) : null,
        }
      }
      return d
    })

    setDives(updatedDives)
  }

  const submitScores = async () => {
    if (!selectedDive) return

    try {
      setSubmitting(true)
      await api.post(`/api/v1/dives/${selectedDiveId}/judge-scores`, {
        judge_scores: selectedDive.judge_scores,
      })

      if (onScoreSubmitted) {
        onScoreSubmitted(selectedDiveId)
      }

      setError(null)
      alert('Scores submitted successfully!')
      setSelectedDiveId(null)
    } catch (err) {
      console.error('Error submitting scores:', err)
      setError('Failed to submit scores')
    } finally {
      setSubmitting(false)
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse bg-gray-700 h-20 rounded-lg"></div>
        ))}
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

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
      {/* Dive List */}
      <div className="lg:col-span-1">
        <h3 className="font-bold text-gray-300 mb-4">Dives to Score</h3>
        <div className="space-y-2">
          {dives.map((dive) => (
            <button
              key={dive.dive_id}
              onClick={() => setSelectedDiveId(dive.dive_id)}
              className={`w-full text-left p-4 rounded-lg border transition-colors ${
                selectedDiveId === dive.dive_id
                  ? 'bg-cyan-500/20 border-cyan-500/50'
                  : 'bg-gray-800/50 border-gray-700 hover:bg-gray-800'
              }`}
            >
              <p className="font-semibold text-cyan-400">{dive.dive_code}</p>
              <p className="text-xs text-gray-500">{dive.height}</p>
              <div className="mt-2 flex items-center justify-between">
                <span className="text-xs text-gray-400">DD: {dive.dd_value}</span>
                {dive.final_score && (
                  <span className={`text-sm font-bold ${dive.final_score >= 25 ? 'text-green-400' : 'text-orange-400'}`}>
                    {dive.final_score.toFixed(2)}
                  </span>
                )}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Scoring Panel */}
      {selectedDive ? (
        <div className="lg:col-span-2 space-y-6">
          {/* Dive Info */}
          <div className="bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border border-cyan-500/30 rounded-lg p-6">
            <h2 className="text-2xl font-bold mb-4">Score Entry: {selectedDive.dive_code}</h2>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <p className="text-gray-500 text-sm">Height</p>
                <p className="text-lg font-bold text-cyan-400">{selectedDive.height}</p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Difficulty</p>
                <p className="text-lg font-bold text-yellow-400">
                  {selectedDive.dd_value.toFixed(1)}
                </p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Judge Count</p>
                <p className="text-lg font-bold text-blue-400">{judgeCount}</p>
              </div>
            </div>
          </div>

          {/* Judge Scores Grid */}
          <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
            <h3 className="font-bold text-gray-300 mb-4">Judge Scores (0-10)</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
              {Array.from({ length: judgeCount }).map((_, idx) => {
                const judgeNumber = idx + 1
                const judgeScore = selectedDive.judge_scores.find(
                  (js) => js.judge_number === judgeNumber
                )
                return (
                  <div key={judgeNumber} className="space-y-2">
                    <label className="text-xs text-gray-500 font-semibold">
                      Judge {judgeNumber}
                    </label>
                    <input
                      type="number"
                      min="0"
                      max="10"
                      step="0.5"
                      value={judgeScore?.score ?? ''}
                      onChange={(e) =>
                        updateJudgeScore(judgeNumber, parseFloat(e.target.value) || 0)
                      }
                      className="w-full bg-gray-800 border border-gray-700 rounded px-2 py-2 text-white text-center font-bold"
                      placeholder="—"
                    />
                  </div>
                )
              })}
            </div>
          </div>

          {/* Calculation */}
          {selectedDive.execution_score !== null && (
            <div className="bg-gradient-to-r from-green-500/10 to-emerald-500/10 border border-green-500/30 rounded-lg p-6 space-y-4">
              <h3 className="font-bold text-green-400">Score Calculation</h3>

              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-gray-400">Judge Scores:</span>
                  <span className="font-mono text-cyan-400">
                    {selectedDive.judge_scores.map((js) => js.score.toFixed(1)).join(', ')}
                  </span>
                </div>

                {selectedDive.judge_scores.length >= 7 && (
                  <div className="text-xs text-gray-500 bg-black/20 rounded p-2">
                    Removed 2 highest and 2 lowest scores
                  </div>
                )}

                <div className="flex items-center justify-between pt-2 border-t border-green-500/30">
                  <span className="text-gray-300">Execution Score:</span>
                  <span className="font-bold text-2xl text-green-400">
                    {selectedDive.execution_score.toFixed(2)}
                  </span>
                </div>

                <div className="flex items-center justify-between">
                  <span className="text-gray-300">Difficulty Multiplier:</span>
                  <span className="font-bold text-xl text-yellow-400">
                    {selectedDive.dd_value.toFixed(1)}×
                  </span>
                </div>

                <div className="flex items-center justify-between pt-2 border-t border-green-500/30">
                  <span className="text-gray-300 font-semibold">Final Score:</span>
                  <span className="font-bold text-3xl text-green-400">
                    {selectedDive.final_score ? selectedDive.final_score.toFixed(2) : '—'}
                  </span>
                </div>
              </div>
            </div>
          )}

          {/* Submit Button */}
          <button
            onClick={submitScores}
            disabled={submitting || !selectedDive.execution_score}
            className="w-full px-4 py-3 bg-green-500/30 hover:bg-green-500/40 text-green-400 rounded font-semibold disabled:opacity-50 transition-colors"
          >
            {submitting ? 'Submitting...' : '✓ Submit Scores'}
          </button>
        </div>
      ) : (
        <div className="lg:col-span-2 flex items-center justify-center bg-gray-800/50 border border-gray-700 rounded-lg h-96">
          <p className="text-gray-400 text-center">
            <p className="mb-2">Select a dive to enter scores</p>
            <p className="text-sm text-gray-500">Each dive is scored by {judgeCount} judges</p>
          </p>
        </div>
      )}
    </div>
  )
}

export default CompetitionScoring
