import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { format, parseISO } from 'date-fns'

interface Dive {
  id: number
  dive_code: string
  performance: string
  performance_numeric: number
  height: string
  dive_datetime: string
  session_id: number
  is_lineup: boolean
  is_sync: boolean
  platform_type: string
  direction: number | null
  official_dd: number | null
  phase1_performance?: string
  phase2_performance?: string
  phase_insight?: string
}

const PERFORMANCE_CONFIG: { [key: string]: { label: string; color: string; bg: string } } = {
  P: { label: 'Perfect', color: 'text-green-400', bg: 'bg-green-500/20' },
  G: { label: 'Good', color: 'text-blue-400', bg: 'bg-blue-500/20' },
  M: { label: 'Medium', color: 'text-amber-400', bg: 'bg-amber-500/20' },
  B: { label: 'Bad', color: 'text-orange-400', bg: 'bg-orange-500/20' },
  F: { label: 'Failed', color: 'text-red-400', bg: 'bg-red-500/20' },
}

const DIRECTION_NAMES: { [key: number]: string } = {
  1: 'Forward',
  2: 'Back',
  3: 'Reverse',
  4: 'Inward',
  5: 'Twist',
}

function Dives() {
  const [dives, setDives] = useState<Dive[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filters, setFilters] = useState({
    height: '',
    performance: '',
    excludeLineup: true,
  })
  const [limit, setLimit] = useState(50)

  useEffect(() => {
    fetchDives()
  }, [filters, limit])

  const fetchDives = async () => {
    try {
      setLoading(true)
      const params: any = { limit }
      if (filters.excludeLineup) params.exclude_lineup = true
      if (filters.height) params.height = filters.height
      if (filters.performance) params.performance = filters.performance

      const response = await api.get('/api/v1/dives', { params })
      setDives(response.data)
      setError(null)
    } catch (err) {
      console.error('Error fetching dives:', err)
      setError('Failed to load dives')
    } finally {
      setLoading(false)
    }
  }

  const uniqueHeights = [...new Set(dives.map(d => d.height))].sort()

  // Stats summary
  const divesWithDD = dives.filter(d => d.official_dd !== null)
  const stats = {
    total: dives.length,
    avgPerformance: dives.length > 0
      ? dives.reduce((sum, d) => sum + d.performance_numeric, 0) / dives.length
      : 0,
    avgDD: divesWithDD.length > 0
      ? divesWithDD.reduce((sum, d) => sum + (d.official_dd || 0), 0) / divesWithDD.length
      : 0,
    maxDD: divesWithDD.length > 0
      ? Math.max(...divesWithDD.map(d => d.official_dd || 0))
      : 0,
    perfect: dives.filter(d => d.performance === 'P').length,
    good: dives.filter(d => d.performance === 'G').length,
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-white">Dive Browser</h1>
          <p className="text-gray-400 mt-1">Explore your training history</p>
        </div>

        {/* Quick Stats */}
        <div className="flex gap-4 flex-wrap">
          <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
            <span className="text-gray-400 text-sm">Dives</span>
            <span className="text-white font-bold ml-2">{stats.total}</span>
          </div>
          <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
            <span className="text-gray-400 text-sm">Avg Performance</span>
            <span className="text-cyan-400 font-bold ml-2">{stats.avgPerformance.toFixed(2)}</span>
          </div>
          {stats.maxDD > 0 && (
            <>
              <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
                <span className="text-gray-400 text-sm">Avg DD</span>
                <span className="text-yellow-400 font-bold ml-2">{stats.avgDD.toFixed(1)}</span>
              </div>
              <div className="bg-gray-800 px-4 py-2 rounded-lg border border-gray-700">
                <span className="text-gray-400 text-sm">Max DD</span>
                <span className="text-orange-400 font-bold ml-2">{stats.maxDD.toFixed(1)}</span>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Filters */}
      <div className="bg-gray-800 rounded-xl p-4 border border-gray-700">
        <div className="flex flex-wrap gap-4 items-center">
          <div>
            <label className="text-gray-400 text-sm block mb-1">Height</label>
            <select
              value={filters.height}
              onChange={(e) => setFilters({ ...filters, height: e.target.value })}
              className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-gray-600 focus:border-cyan-500 focus:outline-none"
            >
              <option value="">All Heights</option>
              <option value="1M">1M</option>
              <option value="3M">3M</option>
              <option value="5M">5M</option>
              <option value="7M">7M</option>
              <option value="10M">10M</option>
            </select>
          </div>

          <div>
            <label className="text-gray-400 text-sm block mb-1">Performance</label>
            <select
              value={filters.performance}
              onChange={(e) => setFilters({ ...filters, performance: e.target.value })}
              className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-gray-600 focus:border-cyan-500 focus:outline-none"
            >
              <option value="">All Levels</option>
              <option value="P">Perfect</option>
              <option value="G">Good</option>
              <option value="M">Medium</option>
              <option value="B">Bad</option>
              <option value="F">Failed</option>
            </select>
          </div>

          <div>
            <label className="text-gray-400 text-sm block mb-1">Show</label>
            <select
              value={limit}
              onChange={(e) => setLimit(Number(e.target.value))}
              className="bg-gray-700 text-white rounded-lg px-3 py-2 border border-gray-600 focus:border-cyan-500 focus:outline-none"
            >
              <option value={25}>25 dives</option>
              <option value={50}>50 dives</option>
              <option value={100}>100 dives</option>
              <option value={200}>200 dives</option>
            </select>
          </div>

          <div className="flex items-end">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={filters.excludeLineup}
                onChange={(e) => setFilters({ ...filters, excludeLineup: e.target.checked })}
                className="w-4 h-4 rounded border-gray-600 text-cyan-500 focus:ring-cyan-500 bg-gray-700"
              />
              <span className="text-gray-300 text-sm">Hide lineups</span>
            </label>
          </div>
        </div>
      </div>

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="w-12 h-12 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-xl p-4 text-red-400">
          {error}
        </div>
      )}

      {/* Dives Grid */}
      {!loading && !error && (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
          {dives.map((dive) => {
            const perfConfig = PERFORMANCE_CONFIG[dive.performance] || PERFORMANCE_CONFIG.M
            return (
              <div
                key={dive.id}
                className="bg-gray-800 rounded-xl p-4 border border-gray-700 hover:border-gray-600 transition group"
              >
                <div className="flex items-start justify-between mb-3">
                  <div>
                    <span className="text-2xl font-bold text-white">{dive.dive_code}</span>
                    {dive.is_lineup && (
                      <span className="ml-2 text-xs bg-purple-500/20 text-purple-400 px-2 py-0.5 rounded">
                        Lineup
                      </span>
                    )}
                    {dive.is_sync && (
                      <span className="ml-2 text-xs bg-blue-500/20 text-blue-400 px-2 py-0.5 rounded">
                        Sync
                      </span>
                    )}
                  </div>
                  <span className={`px-3 py-1 rounded-lg text-sm font-medium ${perfConfig.bg} ${perfConfig.color}`}>
                    {perfConfig.label}
                  </span>
                </div>

                <div className="space-y-2 text-sm">
                  <div className="flex justify-between">
                    <span className="text-gray-400">Height</span>
                    <span className="text-white font-medium">{dive.height}</span>
                  </div>
                  {dive.official_dd !== null && (
                    <div className="flex justify-between">
                      <span className="text-gray-400">DD (Difficulty)</span>
                      <span className="text-yellow-400 font-bold text-lg">{dive.official_dd.toFixed(1)}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-400">Platform</span>
                    <span className="text-white capitalize">{dive.platform_type}</span>
                  </div>
                  {dive.direction && (
                    <div className="flex justify-between">
                      <span className="text-gray-400">Direction</span>
                      <span className="text-white">{DIRECTION_NAMES[dive.direction]}</span>
                    </div>
                  )}
                  <div className="flex justify-between">
                    <span className="text-gray-400">Date</span>
                    <span className="text-gray-300">
                      {format(parseISO(dive.dive_datetime), 'MMm d, yyyy')}
                    </span>
                  </div>
                </div>

                {/* Performance bar */}
                <div className="mt-4">
                  <div className="h-1.5 bg-gray-700 rounded-full overflow-hidden">
                    <div
                      className={`h-full rounded-full ${
                        dive.performance_numeric >= 3 ? 'bg-green-500' :
                        dive.performance_numeric >= 2 ? 'bg-amber-500' : 'bg-red-500'
                      }`}
                      style={{ width: `${(dive.performance_numeric / 4) * 100}%` }}
                    />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && dives.length === 0 && (
        <div className="text-center py-16">
          <p className="text-gray-400 text-xl">No dives found</p>
          <p className="text-gray-500 mt-2">Try adjusting your filters</p>
        </div>
      )}

      {/* Load more */}
      {!loading && dives.length >= limit && (
        <div className="text-center">
          <button
            onClick={() => setLimit(limit + 50)}
            className="bg-gray-800 hover:bg-gray-700 text-white px-6 py-2 rounded-lg border border-gray-700 transition"
          >
            Load more dives
          </button>
        </div>
      )}
    </div>
  )
}

export default Dives
