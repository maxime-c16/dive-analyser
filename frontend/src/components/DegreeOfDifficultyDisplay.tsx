import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface DDData {
  code: string
  height: string
  dd_value: number
  platform_type: string
}

interface ScoreCalculation {
  execution_score: number
  dd_value: number
  final_score: number
  breakdown: string
}

interface DegreeOfDifficultyDisplayProps {
  diveCode: string
  height: string
  executionScore?: number
  showCalculation?: boolean
  compact?: boolean
}

function DegreeOfDifficultyDisplay({
  diveCode,
  height,
  executionScore,
  showCalculation = false,
  compact = false,
}: DegreeOfDifficultyDisplayProps) {
  const [ddData, setDDData] = useState<DDData | null>(null)
  const [scoreCalc, setScoreCalc] = useState<ScoreCalculation | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (diveCode && height) {
      fetchDDData()
    }
  }, [diveCode, height])

  const fetchDDData = async () => {
    if (!diveCode || !height) return

    try {
      setLoading(true)
      const response = await api.get(
        `/api/v1/degree-of-difficulty/lookup/${encodeURIComponent(diveCode)}/${encodeURIComponent(height)}`
      )
      setDDData(response.data)

      // If execution score provided, calculate final score
      if (showCalculation && executionScore) {
        setScoreCalc({
          execution_score: executionScore,
          dd_value: response.data.dd_value,
          final_score: executionScore * response.data.dd_value,
          breakdown: `${executionScore.toFixed(2)} × ${response.data.dd_value.toFixed(1)} = ${(executionScore * response.data.dd_value).toFixed(2)}`
        })
      }

      setError(null)
    } catch (err) {
      console.error('Error fetching DD data:', err)
      setError('Unable to load DD information')
    } finally {
      setLoading(false)
    }
  }

  const getDifficultyLevel = (dd: number): string => {
    if (dd < 1.5) return 'Easy'
    if (dd < 2.5) return 'Moderate'
    if (dd < 3.5) return 'Difficult'
    if (dd < 4.5) return 'Very Difficult'
    return 'Elite'
  }

  const getDifficultyIcon = (dd: number): string => {
    if (dd < 1.5) return '🟢'
    if (dd < 2.5) return '🟡'
    if (dd < 3.5) return '🟠'
    if (dd < 4.5) return '🔴'
    return '⭐'
  }

  const getDifficultyColor = (dd: number): string => {
    if (dd < 1.5) return 'text-green-400'
    if (dd < 2.5) return 'text-blue-400'
    if (dd < 3.5) return 'text-yellow-400'
    if (dd < 4.5) return 'text-orange-400'
    return 'text-red-400'
  }

  const getDifficultyBgColor = (dd: number): string => {
    if (dd < 1.5) return 'bg-green-500/10 border-green-500/30'
    if (dd < 2.5) return 'bg-blue-500/10 border-blue-500/30'
    if (dd < 3.5) return 'bg-yellow-500/10 border-yellow-500/30'
    if (dd < 4.5) return 'bg-orange-500/10 border-orange-500/30'
    return 'bg-red-500/10 border-red-500/30'
  }

  if (loading) {
    if (compact) {
      return <div className="animate-pulse bg-gray-700 h-8 rounded w-20"></div>
    }
    return <div className="animate-pulse bg-gray-700 h-32 rounded-lg"></div>
  }

  if (error) {
    if (compact) {
      return <span className="text-red-400 text-xs">—</span>
    }
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    )
  }

  if (!ddData) {
    return <span className="text-gray-400 text-sm">No DD data</span>
  }

  // Compact display (for dive cards, lists)
  if (compact) {
    return (
      <div className="flex items-center gap-2">
        <span className={`text-2xl font-bold ${getDifficultyColor(ddData.dd_value)}`}>
          {ddData.dd_value.toFixed(1)}
        </span>
        <span className="text-2xl">{getDifficultyIcon(ddData.dd_value)}</span>
      </div>
    )
  }

  // Full display
  return (
    <div className={`rounded-lg p-4 border ${getDifficultyBgColor(ddData.dd_value)}`}>
      <div className="flex items-start justify-between mb-3">
        <h3 className="font-bold text-gray-300">Degree of Difficulty</h3>
        <span className="text-2xl">{getDifficultyIcon(ddData.dd_value)}</span>
      </div>

      {/* DD Value and Level */}
      <div className="grid grid-cols-2 gap-4 mb-4">
        <div>
          <p className="text-xs text-gray-500 mb-1">DD Value</p>
          <p className={`text-3xl font-bold ${getDifficultyColor(ddData.dd_value)}`}>
            {ddData.dd_value.toFixed(1)}
          </p>
        </div>
        <div>
          <p className="text-xs text-gray-500 mb-1">Difficulty Level</p>
          <p className={`text-lg font-bold ${getDifficultyColor(ddData.dd_value)}`}>
            {getDifficultyLevel(ddData.dd_value)}
          </p>
        </div>
      </div>

      {/* Height and Platform */}
      <div className="bg-black/20 rounded p-2 mb-4 text-sm">
        <p className="text-gray-400">
          <span className="font-semibold">{diveCode}</span> from{' '}
          <span className="font-semibold text-cyan-400">{height}</span>
        </p>
        <p className="text-xs text-gray-500 mt-1">
          {ddData.platform_type === 'springboard' ? '🏊 Springboard' : '🏔️ Platform'}
        </p>
      </div>

      {/* Difficulty Scale Visualization */}
      <div className="mb-4">
        <p className="text-xs text-gray-500 mb-2 font-semibold">Difficulty Scale</p>
        <div className="flex items-center gap-1">
          {[
            { label: 'Easy', value: 1.0, color: 'bg-green-500/30' },
            { label: 'Moderate', value: 2.0, color: 'bg-blue-500/30' },
            { label: 'Difficult', value: 3.0, color: 'bg-yellow-500/30' },
            { label: 'Very Diff.', value: 4.0, color: 'bg-orange-500/30' },
            { label: 'Elite', value: 5.0, color: 'bg-red-500/30' },
          ].map((level, idx) => (
            <div
              key={idx}
              className={`flex-1 h-2 rounded transition-all ${
                ddData.dd_value >= level.value
                  ? `${level.color} opacity-100`
                  : 'bg-gray-700 opacity-30'
              }`}
            ></div>
          ))}
        </div>
      </div>

      {/* Calculation Display */}
      {showCalculation && scoreCalc && (
        <div className="bg-black/20 rounded p-4 border-t border-gray-700 mt-4">
          <h4 className="font-bold text-gray-300 mb-3">Score Calculation</h4>
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Execution Score:</span>
              <span className="font-bold text-cyan-400">{scoreCalc.execution_score.toFixed(2)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-gray-400">Difficulty Multiplier:</span>
              <span className="font-bold text-yellow-400">{scoreCalc.dd_value.toFixed(1)}×</span>
            </div>
            <div className="flex items-center justify-between pt-2 border-t border-gray-700">
              <span className="text-gray-300 font-semibold">Final Score:</span>
              <span className={`text-2xl font-bold ${getDifficultyColor(scoreCalc.dd_value)}`}>
                {scoreCalc.final_score.toFixed(2)}
              </span>
            </div>
            <p className="text-xs text-gray-500 mt-2 italic">
              {scoreCalc.breakdown}
            </p>
          </div>
        </div>
      )}

      {/* Information */}
      <div className="bg-black/10 rounded p-3 text-xs text-gray-400 mt-4 border border-gray-700">
        <p>
          Official FINA Degree of Difficulty ({ddData.platform_type}). Used in official competitions to adjust raw
          performance scores.
        </p>
      </div>
    </div>
  )
}

export default DegreeOfDifficultyDisplay
