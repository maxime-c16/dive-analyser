import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { ArrowLeft } from 'lucide-react'

interface Chapter {
  number: number
  date: string
  title: string
  result: string
  narrative: string
}

interface DiveStoryData {
  dive_code: string
  height: string
  opening: string
  chapters: Chapter[]
  closing: string
  stats: {
    total_attempts: number
    successes: number
    success_rate: number
    perfects: number
    smacks: number
    smacks_recovered_from: number
  }
  current_streak: number
}

interface DiveStoryProps {
  diveCode: string
  height: string
  onClose: () => void
}

const getPerformanceColor = (result: string): string => {
  const colors: { [key: string]: string } = {
    'Failed': 'text-red-400 bg-red-500/10',
    'Bad': 'text-orange-400 bg-orange-500/10',
    'Medium': 'text-amber-400 bg-amber-500/10',
    'Good': 'text-green-400 bg-green-500/10',
    'Perfect': 'text-cyan-400 bg-cyan-500/10',
  }
  return colors[result] || 'text-gray-400 bg-gray-500/10'
}

const getPerformanceEmoji = (result: string): string => {
  const emojis: { [key: string]: string } = {
    'Failed': '❌',
    'Bad': '⚠️',
    'Medium': '➡️',
    'Good': '✅',
    'Perfect': '💎',
  }
  return emojis[result] || '•'
}

function DiveStory({ diveCode, height, onClose }: DiveStoryProps) {
  const [data, setData] = useState<DiveStoryData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedChapter, setExpandedChapter] = useState<number | null>(null)

  useEffect(() => {
    fetchDiveStory()
  }, [diveCode, height])

  const fetchDiveStory = async () => {
    try {
      setLoading(true)
      const response = await api.get(`/api/v1/journey/dive/${diveCode}/${height}`)
      setData(response.data)
      setError(null)
    } catch (err) {
      console.error('Error fetching dive story:', err)
      setError('Failed to load dive story')
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div className="bg-gray-900 rounded-lg max-w-2xl w-full max-h-[90vh] overflow-auto p-6">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-gray-700 rounded w-1/2"></div>
            <div className="h-4 bg-gray-700 rounded w-3/4"></div>
            <div className="space-y-3 mt-6">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-20 bg-gray-700 rounded"></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div className="bg-gray-900 rounded-lg max-w-2xl w-full p-6">
          <button
            onClick={onClose}
            className="mb-4 flex items-center gap-2 text-gray-400 hover:text-white transition"
          >
            <ArrowLeft size={18} />
            Back
          </button>
          <div className="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-400">
            {error || 'Failed to load dive story'}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-gray-900 rounded-lg max-w-3xl w-full max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="sticky top-0 bg-gradient-to-b from-gray-900 to-gray-900/80 border-b border-gray-700 p-6 flex items-center justify-between">
          <div>
            <h2 className="text-2xl font-bold">
              {data.dive_code}
              <span className="text-lg text-gray-400 ml-3">{data.height}</span>
            </h2>
            <p className="text-gray-400 text-sm mt-1">Your complete journey with this dive</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 hover:bg-gray-800 rounded transition text-gray-400 hover:text-white"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="p-6 space-y-8">
          {/* Opening */}
          <div className="bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border border-cyan-500/30 rounded-lg p-6">
            <p className="text-lg text-gray-100 italic leading-relaxed">
              {data.opening}
            </p>
          </div>

          {/* Stats Grid */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-400 text-xs uppercase tracking-wide mb-1">Total Attempts</div>
              <div className="text-2xl font-bold text-cyan-400">{data.stats.total_attempts}</div>
            </div>
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-400 text-xs uppercase tracking-wide mb-1">Successes</div>
              <div className="text-2xl font-bold text-green-400">{data.stats.successes}</div>
            </div>
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-400 text-xs uppercase tracking-wide mb-1">Success Rate</div>
              <div className="text-2xl font-bold text-amber-400">{data.stats.success_rate}%</div>
            </div>
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-400 text-xs uppercase tracking-wide mb-1">Current Streak</div>
              <div className="text-2xl font-bold text-purple-400">{data.current_streak}</div>
            </div>
          </div>

          {/* Chapters */}
          <div className="space-y-3">
            <h3 className="text-lg font-bold mb-4">Your Journey</h3>
            {data.chapters.map((chapter) => (
              <div
                key={chapter.number}
                className="border border-gray-700 rounded-lg overflow-hidden hover:border-gray-600 transition bg-gray-900/50"
              >
                <button
                  onClick={() => setExpandedChapter(
                    expandedChapter === chapter.number ? null : chapter.number
                  )}
                  className="w-full p-4 flex items-start justify-between hover:bg-gray-800/50 transition text-left"
                >
                  <div className="flex items-start gap-4 flex-1">
                    <div className="flex items-center gap-2 flex-shrink-0">
                      <span className="text-sm font-bold text-gray-400 w-8">#{chapter.number}</span>
                      <span className={`px-2 py-1 rounded text-xs font-bold ${getPerformanceColor(chapter.result)}`}>
                        {getPerformanceEmoji(chapter.result)} {chapter.result}
                      </span>
                    </div>
                    <div className="flex-1">
                      <h4 className="font-semibold text-gray-100 mb-1">{chapter.title}</h4>
                      <p className="text-gray-400 text-sm">{chapter.date}</p>
                    </div>
                  </div>
                  <div className={`transform transition ${expandedChapter === chapter.number ? 'rotate-180' : ''}`}>
                    <span className="text-gray-400">▼</span>
                  </div>
                </button>

                {expandedChapter === chapter.number && (
                  <div className="border-t border-gray-700 bg-gray-950 p-4">
                    <p className="text-gray-300 leading-relaxed">{chapter.narrative}</p>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Closing */}
          <div className="bg-gradient-to-r from-amber-500/10 to-orange-500/10 border border-amber-500/30 rounded-lg p-6">
            <p className="text-lg text-gray-100 italic leading-relaxed">
              {data.closing}
            </p>
          </div>

          {/* Additional Stats */}
          <div className="grid md:grid-cols-2 gap-4 pt-4 border-t border-gray-700">
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-400 text-xs uppercase tracking-wide mb-2">Perfect Attempts</div>
              <div className="text-2xl font-bold text-cyan-400">{data.stats.perfects}</div>
            </div>
            <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
              <div className="text-gray-400 text-xs uppercase tracking-wide mb-2">Smacks</div>
              <div className="text-2xl font-bold text-red-400">{data.stats.smacks}</div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default DiveStory
