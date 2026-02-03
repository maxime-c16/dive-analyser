import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { AlertCircle } from 'lucide-react'

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
          <div key={i} className="h-24 bg-gray-700 rounded"></div>
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
      <div className="text-center py-12 bg-gray-900/50 border border-gray-700 rounded-lg">
        <div className="text-gray-400 mb-4">✅</div>
        <p className="text-gray-300 mb-2 font-semibold">No avoided dives detected</p>
        <p className="text-gray-500 text-sm">You're keeping up with your dives. That's consistency.</p>
      </div>
    )
  }

  const sorted = getSortedDives()

  return (
    <div className="space-y-6">
      {/* Header and Filter */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold mb-2">Patterns in Your Practice</h2>
          <p className="text-gray-400 text-sm">
            {data.total_avoided} dive{data.total_avoided !== 1 ? 's' : ''} haven't been attempted recently.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setSortBy('score')}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              sortBy === 'score'
                ? 'bg-cyan-500 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            Avoidance Score
          </button>
          <button
            onClick={() => setSortBy('days')}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              sortBy === 'days'
                ? 'bg-cyan-500 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            Days Away
          </button>
          <button
            onClick={() => setSortBy('difficulty')}
            className={`px-4 py-2 rounded text-sm font-medium transition-colors ${
              sortBy === 'difficulty'
                ? 'bg-cyan-500 text-white'
                : 'bg-gray-800 text-gray-300 hover:bg-gray-700'
            }`}
          >
            Difficulty
          </button>
        </div>
      </div>

      {/* Encouragement Message */}
      <div className="bg-gradient-to-r from-blue-500/10 to-cyan-500/10 border border-blue-500/30 rounded-lg p-4">
        <p className="text-gray-300 italic text-center">{data.encouragement}</p>
      </div>

      {/* Avoided Dives List */}
      <div className="space-y-3">
        {sorted.map((dive, index) => (
          <div
            key={`${dive.dive_code}-${dive.height}-${index}`}
            className={`border border-gray-700 rounded-lg overflow-hidden transition-all hover:border-gray-600 ${getDifficultyBg(dive.failure_rate / 100)}`}
          >
            <div className="p-4 md:p-6 space-y-3">
              {/* Top Row: Code, Days, Difficulty */}
              <div className="flex flex-col md:flex-row md:items-center justify-between gap-3">
                <div className="flex items-center gap-4">
                  <div className="text-2xl font-bold text-cyan-400">
                    {dive.dive_code}
                    <span className="text-lg text-gray-400 ml-2">{dive.height}</span>
                  </div>
                </div>

                <div className="flex flex-wrap gap-4 text-sm">
                  <div>
                    <div className="text-gray-400 text-xs mb-1">Days Without Attempt</div>
                    <div className="font-bold text-amber-400">{dive.days_since_attempt} days</div>
                  </div>
                  <div>
                    <div className="text-gray-400 text-xs mb-1">Attempts</div>
                    <div className="font-bold text-gray-300">{dive.total_attempts}</div>
                  </div>
                  <div>
                    <div className="text-gray-400 text-xs mb-1">Difficulty</div>
                    <div className={`font-bold ${getDifficultyColor(dive.failure_rate / 100)}`}>
                      {Math.round(dive.failure_rate)}%
                    </div>
                  </div>
                  <div>
                    <div className="text-gray-400 text-xs mb-1">Avoidance Score</div>
                    <div className="font-bold text-gray-300">{dive.avoidance_score.toFixed(1)}</div>
                  </div>
                </div>
              </div>

              {/* Message */}
              <div className="border-t border-gray-700 pt-3">
                <p className="text-gray-300 text-sm">{dive.message}</p>
              </div>

              {/* Last Performance */}
              <div className="flex items-center gap-2 text-xs text-gray-400">
                <AlertCircle size={14} />
                <span>Last performance: <span className="font-mono text-gray-300">{getPerformanceLabel(dive.last_performance)}</span></span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Insight Box */}
      <div className="bg-gray-900/50 border border-gray-700 rounded-lg p-6">
        <h3 className="font-bold mb-3 text-gray-200">Understanding These Patterns</h3>
        <ul className="space-y-2 text-sm text-gray-300">
          <li className="flex gap-2">
            <span className="text-cyan-400">→</span>
            <span><strong>Avoidance Score</strong> combines how long it's been and how difficult the dive is. Higher = stronger pattern of avoidance.</span>
          </li>
          <li className="flex gap-2">
            <span className="text-cyan-400">→</span>
            <span><strong>High Difficulty</strong> dives (70%+) might warrant focused practice or technique refinement before returning.</span>
          </li>
          <li className="flex gap-2">
            <span className="text-cyan-400">→</span>
            <span><strong>Mixed Results</strong> dives (50-70%) often benefit from lineups or partial attempts to rebuild confidence.</span>
          </li>
          <li className="flex gap-2">
            <span className="text-cyan-400">→</span>
            <span><strong>Low Difficulty</strong> dives (under 50%) are worth revisiting — they're often easier than you remember.</span>
          </li>
        </ul>
      </div>
    </div>
  )
}

export default AvoidedDives
