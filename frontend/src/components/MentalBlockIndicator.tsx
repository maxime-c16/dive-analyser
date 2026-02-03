import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface MentalBlock {
  type: 'dd_plateau' | 'repeated_failure' | 'avoided_dive'
  description: string
  dives_affected: string[]
  duration_months: number
  recommendations: string[]
}

function MentalBlockIndicator() {
  const [blocks, setBlocks] = useState<MentalBlock[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    fetchMentalBlocks()
  }, [])

  const fetchMentalBlocks = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/psychology/mental-blocks')
      setBlocks(response.data.blocks || [])
      setError(null)
    } catch (err) {
      // Mental blocks endpoint may not exist yet - silently handle
      console.debug('Mental blocks data not available yet')
      setBlocks([])
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="animate-pulse bg-gray-800 rounded-lg p-4 h-24 border border-gray-700"></div>
    )
  }

  if (blocks.length === 0) {
    return (
      <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
        <div className="text-green-400 font-bold">✅ No Mental Blocks Detected</div>
        <p className="text-green-300 text-sm mt-1">
          You're progressing smoothly! Keep challenging yourself.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {blocks.map((block, idx) => {
        const blockKey = `block-${idx}`
        const isExpanded = expanded === blockKey

        return (
          <div
            key={blockKey}
            className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg overflow-hidden"
          >
            <button
              onClick={() => setExpanded(isExpanded ? null : blockKey)}
              className="w-full p-4 flex items-start justify-between hover:bg-yellow-500/5 transition-colors"
            >
              <div className="text-left">
                <div className="text-yellow-400 font-bold flex items-center gap-2">
                  <span>⚠️</span>
                  {block.type === 'dd_plateau' && 'Difficulty Plateau'}
                  {block.type === 'repeated_failure' && 'Repeated Failure Pattern'}
                  {block.type === 'avoided_dive' && 'Avoided Dive'}
                </div>
                <p className="text-yellow-300 text-sm mt-1">{block.description}</p>
                <div className="text-xs text-gray-400 mt-2">
                  {block.duration_months} month{block.duration_months !== 1 ? 's' : ''} • Affecting{' '}
                  {block.dives_affected.length} dive{block.dives_affected.length !== 1 ? 's' : ''}
                </div>
              </div>
              <div className="text-xl text-yellow-400 ml-4">
                {isExpanded ? '▼' : '▶'}
              </div>
            </button>

            {isExpanded && (
              <div className="bg-yellow-500/5 border-t border-yellow-500/30 p-4 space-y-4">
                {/* Affected Dives */}
                <div>
                  <h4 className="text-sm font-bold text-yellow-400 mb-2">Affected Dives:</h4>
                  <div className="flex flex-wrap gap-2">
                    {block.dives_affected.map((dive) => (
                      <span
                        key={dive}
                        className="text-xs bg-yellow-500/20 text-yellow-300 px-3 py-1 rounded"
                      >
                        {dive}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Recommendations */}
                <div>
                  <h4 className="text-sm font-bold text-green-400 mb-2">Recovery Plan:</h4>
                  <div className="space-y-2">
                    {block.recommendations.map((rec, recIdx) => (
                      <div
                        key={recIdx}
                        className="text-sm text-gray-300 flex items-start gap-2"
                      >
                        <span className="text-green-400 font-bold mt-0.5">•</span>
                        <span>{rec}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Encouragement */}
                <div className="bg-green-500/10 border border-green-500/30 rounded p-3">
                  <p className="text-green-300 text-sm">
                    <strong>Remember:</strong> Mental blocks are natural and temporary. Every breakthrough starts with
                    facing a challenge. You've overcome obstacles before—you can do this too! 💪
                  </p>
                </div>

                {/* Action Button */}
                <div className="flex gap-2">
                  <button
                    onClick={() => fetchMentalBlocks()}
                    className="flex-1 py-2 px-3 bg-yellow-600 hover:bg-yellow-700 text-white rounded text-sm font-medium transition-colors"
                  >
                    Check Progress
                  </button>
                  <button
                    onClick={() => setExpanded(null)}
                    className="flex-1 py-2 px-3 bg-gray-700 hover:bg-gray-600 text-gray-300 rounded text-sm font-medium transition-colors"
                  >
                    Dismiss
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default MentalBlockIndicator
