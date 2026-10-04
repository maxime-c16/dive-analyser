import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { AlertCircle, CheckCircle2 } from 'lucide-react'

interface AvoidedDive {
  dive_code: string
  height: string
  days_since_attempt: number
  total_attempts: number
  failure_rate: number
  last_performance: string
  avoidance_score: number
  message: string
}

interface AvoidedDivesResponse {
  total_avoided: number
  avoided: AvoidedDive[]
  encouragement: string
}

function AvoidedDives() {
  const [data, setData] = useState<AvoidedDivesResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<'score' | 'days' | 'difficulty'>('score')

  useEffect(() => {
    fetchAvoidedDives()
  }, [])

  const fetchAvoidedDives = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/journey/avoided')
      setData(response.data)
      setError(null)
    } catch (err) {
      console.error('Error fetching avoided dives:', err)
      setError('Failed to load avoided dives analysis')
    } finally {
      setLoading(false)
    }
  }

  const getSortedDives = (): AvoidedDive[] => {
    if (!data) return []
    const dives = [...data.avoided]
    if (sortBy === 'score') {
      return dives.sort((a, b) => b.avoidance_score - a.avoidance_score)
    } else if (sortBy === 'days') {
      return dives.sort((a, b) => b.days_since_attempt - a.days_since_attempt)
    } else {
      return dives.sort((a, b) => b.failure_rate - a.failure_rate)
    }
  }

  const getPerformanceLabel = (perf: string): string => {
    const labels: { [key: string]: string } = {
      'F': 'Failed',
      'B': 'Bad',
      'M': 'Medium',
      'G': 'Good',
      'P': 'Perfect',
    }
    return labels[perf] || perf
  }

  const getDifficultyColor = (rate: number): string => {
    if (rate > 0.7) return 'text-red-400'
    if (rate > 0.5) return 'text-amber-400'
    return 'text-yellow-400'
  }

  const getDifficultyBg = (rate: number): string => {
    if (rate > 0.7) return 'bg-red-500/10'
    if (rate > 0.5) return 'bg-amber-500/10'
    return 'bg-yellow-500/10'
  }

  if (loading) {
    return (
      <div className="animate-pulse space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-24 bg-app-panel-elevated rounded"></div>
        ))}
      </div>
    )
  }

  if (error) {
    return (
      <div className="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-400">
        {error}
      </div>
    )
  }

  if (!data || data.total_avoided === 0) {
    return (
      <div className="text-center py-12 bg-app-panel border border-app rounded-lg">
        <CheckCircle2 className="mx-auto mb-4 h-7 w-7 text-green-400" aria-hidden="true" />
        <p className="text-app-text font-semibold">No avoided dives.</p>
      </div>
    )
  }

  const sorted = getSortedDives()

  return (
    <div className="space-y-6">
      {/* Header and Filter */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold mb-2">Avoided Dives</h2>
          <p className="text-app-muted text-sm">
            {data.total_avoided} dive{data.total_avoided !== 1 ? 's' : ''} not attempted recently.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setSortBy('score')}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              sortBy === 'score'
                ? 'bg-app-accent text-app-bg'
                : 'bg-app-panel-elevated text-app-muted hover:text-app-text'
            }`}
          >
            Avoidance Score
          </button>
          <button
            onClick={() => setSortBy('days')}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              sortBy === 'days'
                ? 'bg-app-accent text-app-bg'
                : 'bg-app-panel-elevated text-app-muted hover:text-app-text'
            }`}
          >
            Days Away
          </button>
          <button
            onClick={() => setSortBy('difficulty')}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              sortBy === 'difficulty'
                ? 'bg-app-accent text-app-bg'
                : 'bg-app-panel-elevated text-app-muted hover:text-app-text'
            }`}
          >
            Difficulty
          </button>
        </div>
      </div>

      {/* Avoided Dives List */}
      <div className="space-y-3">
        {sorted.map((dive, index) => (
          <div
            key={`${dive.dive_code}-${dive.height}-${index}`}
            className={`border border-app rounded-lg overflow-hidden transition-all hover:border-app-strong ${getDifficultyBg(dive.failure_rate / 100)}`}
          >
            <div className="p-4 md:p-6 space-y-3">
              {/* Top Row: Code, Days, Difficulty */}
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                <div className="flex items-center gap-4">
                  <div className="text-2xl font-bold text-app-accent">
                    {dive.dive_code}
                    <span className="text-lg text-app-muted ml-2">{dive.height}</span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-4 text-sm">
                  <div>
                    <div className="text-app-muted text-xs mb-1">Days Without Attempt</div>
                    <div className="font-bold text-amber-400">{dive.days_since_attempt} days</div>
                  </div>
                  <div>
                    <div className="text-app-muted text-xs mb-1">Attempts</div>
                    <div className="font-bold text-app-text">{dive.total_attempts}</div>
                  </div>
                  <div>
                    <div className="text-app-muted text-xs mb-1">Difficulty</div>
                    <div className={`font-bold ${getDifficultyColor(dive.failure_rate / 100)}`}>
                      {Math.round(dive.failure_rate)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-app-muted text-xs mb-1">Avoidance Score</div>
                    <div className="font-bold text-app-text">{dive.avoidance_score.toFixed(1)}</div>
                  </div>
                </div>
              </div>

              {/* Message */}
              <div className="border-t border-app pt-3">
                <p className="text-app-text text-sm">{dive.message}</p>
              </div>

              {/* Last Performance */}
              <div className="flex items-center gap-2 text-xs text-app-muted">
                <AlertCircle size={14} />
                <span>Last performance: <span className="font-mono text-app-text">{getPerformanceLabel(dive.last_performance)}</span></span>
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default AvoidedDives
