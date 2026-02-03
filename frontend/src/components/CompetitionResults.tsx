import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface ParticipantScore {
  rank: number
  name: string
  level: string
  total_score: number
  dive_count: number
  average_score: number
  dives: Array<{
    dive_code: string
    height: string
    dd_value: number
    score: number
  }>
}

interface CompetitionResultsProps {
  eventId: number
  onExport?: () => void
}

function CompetitionResults({ eventId, onExport }: CompetitionResultsProps) {
  const [results, setResults] = useState<ParticipantScore[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedParticipant, setExpandedParticipant] = useState<number | null>(null)
  const [exportFormat, setExportFormat] = useState<'pdf' | 'csv'>('pdf')

  useEffect(() => {
    fetchResults()
  }, [eventId])

  const fetchResults = async () => {
    try {
      setLoading(true)
      const response = await api.get(`/api/v1/events/${eventId}/results`)
      setResults(response.data.rankings || [])
      setError(null)
    } catch (err) {
      console.error('Error fetching results:', err)
      setError('Failed to load results')
    } finally {
      setLoading(false)
    }
  }

  const handleExport = async (format: 'pdf' | 'csv') => {
    try {
      const response = await api.get(
        `/api/v1/events/${eventId}/results/export?format=${format}`,
        {
          responseType: format === 'pdf' ? 'blob' : 'text',
        }
      )

      // Create download link
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `results.${format}`)
      document.body.appendChild(link)
      link.click()
      link.parentNode?.removeChild(link)
    } catch (err) {
      console.error('Error exporting results:', err)
      alert('Failed to export results')
    }
  }

  if (loading) {
    return (
      <div className="space-y-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="animate-pulse bg-gray-700 h-24 rounded-lg"></div>
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

  if (results.length === 0) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 text-center">
        <p className="text-gray-400">No results available yet.</p>
      </div>
    )
  }

  // Get medals
  const getMedalColor = (rank: number): string => {
    if (rank === 1) return 'from-yellow-400 to-yellow-600'
    if (rank === 2) return 'from-gray-300 to-gray-500'
    if (rank === 3) return 'from-orange-400 to-orange-600'
    return 'from-gray-700 to-gray-800'
  }

  const getMedalIcon = (rank: number): string => {
    if (rank === 1) return '🥇'
    if (rank === 2) return '🥈'
    if (rank === 3) return '🥉'
    return '•'
  }

  return (
    <div className="space-y-6">
      {/* Export Controls */}
      <div className="flex items-center justify-between gap-4 bg-gray-800/50 border border-gray-700 rounded-lg p-4">
        <p className="text-gray-400 font-semibold">Export Results</p>
        <div className="flex gap-2">
          <button
            onClick={() => handleExport('pdf')}
            className="px-4 py-2 bg-red-500/30 hover:bg-red-500/40 text-red-400 rounded text-sm font-semibold transition-colors"
          >
            📄 PDF
          </button>
          <button
            onClick={() => handleExport('csv')}
            className="px-4 py-2 bg-blue-500/30 hover:bg-blue-500/40 text-blue-400 rounded text-sm font-semibold transition-colors"
          >
            📊 CSV
          </button>
        </div>
      </div>

      {/* Podium */}
      {results.length >= 1 && (
        <div className="bg-gradient-to-b from-yellow-500/10 to-gray-900 border border-yellow-500/20 rounded-lg p-8">
          <h3 className="font-bold text-yellow-400 text-center mb-8">🏆 Final Rankings</h3>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {/* Gold */}
            {results[0] && (
              <div className="text-center space-y-3 order-2 md:order-1">
                <div
                  className={`bg-gradient-to-b ${getMedalColor(2)} rounded-lg p-6`}
                >
                  <p className="text-white text-lg font-bold">{results[1]?.name || '—'}</p>
                  <p className="text-gray-900 text-2xl font-bold mt-2">
                    {results[1]?.total_score.toFixed(2) || '—'}
                  </p>
                  <p className="text-4xl mt-2">🥈</p>
                </div>
              </div>
            )}

            {/* Silver (middle) */}
            {results[0] && (
              <div className="text-center space-y-3 order-1 md:order-2">
                <div
                  className={`bg-gradient-to-b ${getMedalColor(1)} rounded-lg p-8`}
                >
                  <p className="text-gray-900 font-bold text-lg">1st Place</p>
                  <p className="text-gray-900 text-2xl font-bold mt-2">
                    {results[0].name}
                  </p>
                  <p className="text-gray-900 text-3xl font-bold mt-2">
                    {results[0].total_score.toFixed(2)}
                  </p>
                  <p className="text-5xl mt-2">🥇</p>
                </div>
              </div>
            )}

            {/* Bronze */}
            {results[2] && (
              <div className="text-center space-y-3 order-3">
                <div
                  className={`bg-gradient-to-b ${getMedalColor(3)} rounded-lg p-6`}
                >
                  <p className="text-white text-lg font-bold">{results[2].name}</p>
                  <p className="text-gray-100 text-2xl font-bold mt-2">
                    {results[2].total_score.toFixed(2)}
                  </p>
                  <p className="text-4xl mt-2">🥉</p>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Full Rankings */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
        <h3 className="font-bold text-gray-300 mb-4">All Results</h3>
        <div className="space-y-3">
          {results.map((participant) => {
            const isExpanded = expandedParticipant === participant.rank

            return (
              <div key={participant.rank} className="border border-gray-700 rounded-lg overflow-hidden">
                <button
                  onClick={() =>
                    setExpandedParticipant(
                      isExpanded ? null : participant.rank
                    )
                  }
                  className="w-full p-4 hover:bg-gray-800/50 transition-colors flex items-center justify-between text-left"
                >
                  <div className="flex items-center gap-4 flex-1">
                    <div className="text-2xl">{getMedalIcon(participant.rank)}</div>
                    <div>
                      <p className="font-bold text-gray-200 text-lg">
                        #{participant.rank} - {participant.name}
                      </p>
                      <p className="text-xs text-gray-500 capitalize mt-1">
                        {participant.level} • {participant.dive_count} dives
                      </p>
                    </div>
                  </div>
                  <div className="text-right">
                    <p className="text-2xl font-bold text-cyan-400">
                      {participant.total_score.toFixed(2)}
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      Avg: {participant.average_score.toFixed(2)}
                    </p>
                  </div>
                  <span className="text-gray-500 ml-4">{isExpanded ? '▼' : '▶'}</span>
                </button>

                {/* Dive Breakdown */}
                {isExpanded && (
                  <div className="border-t border-gray-700 bg-gray-800/30 p-4 space-y-2">
                    <p className="text-xs font-semibold text-gray-500 mb-3">Dive Breakdown</p>
                    {participant.dives.map((dive, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between text-sm bg-gray-800/50 rounded p-2"
                      >
                        <div>
                          <span className="font-mono text-cyan-400">
                            {dive.dive_code}
                          </span>
                          <span className="text-gray-500 ml-2">@ {dive.height}</span>
                        </div>
                        <div className="flex items-center gap-3">
                          <span className="text-yellow-400 font-semibold">
                            DD {dive.dd_value.toFixed(1)}×
                          </span>
                          <span className="text-green-400 font-bold">
                            {dive.score.toFixed(2)}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      </div>

      {/* Statistics */}
      {results.length > 0 && (
        <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-6 space-y-3">
          <h3 className="font-bold text-blue-400 mb-3">Statistics</h3>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <p className="text-gray-500">Total Competitors</p>
              <p className="text-2xl font-bold text-blue-400">{results.length}</p>
            </div>
            <div>
              <p className="text-gray-500">Highest Score</p>
              <p className="text-2xl font-bold text-green-400">
                {Math.max(...results.map((r) => r.total_score)).toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Lowest Score</p>
              <p className="text-2xl font-bold text-orange-400">
                {Math.min(...results.map((r) => r.total_score)).toFixed(2)}
              </p>
            </div>
            <div>
              <p className="text-gray-500">Average Score</p>
              <p className="text-2xl font-bold text-cyan-400">
                {(
                  results.reduce((sum, r) => sum + r.total_score, 0) / results.length
                ).toFixed(2)}
              </p>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default CompetitionResults
