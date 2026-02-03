import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface ComplianceStats {
  total_dives: number
  valid_dives: number
  invalid_dives: number
  validity_percentage: number
  by_height: { [key: string]: { valid: number; invalid: number } }
  by_group: { [key: string]: { valid: number; invalid: number } }
  problematic_dives: Array<{
    id: number
    dive_code: string
    height: string
    error: string
  }>
}

interface ComplianceDashboardProps {
  minimal?: boolean
}

function ComplianceDashboard({ minimal = false }: ComplianceDashboardProps) {
  const [stats, setStats] = useState<ComplianceStats | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expandedSection, setExpandedSection] = useState<string | null>('overview')

  useEffect(() => {
    fetchComplianceStats()
  }, [])

  const fetchComplianceStats = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/admin/validate-dives')
      setStats(response.data)
      setError(null)
    } catch (err) {
      console.error('Error fetching compliance stats:', err)
      setError('Failed to load compliance data')
    } finally {
      setLoading(false)
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

  if (!stats) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
        <p className="text-gray-400">No compliance data available</p>
      </div>
    )
  }

  const validPercentage = stats.validity_percentage

  if (minimal) {
    // Compact version for dashboard widgets
    return (
      <div className={`rounded-lg p-6 border ${
        validPercentage >= 95
          ? 'bg-green-500/10 border-green-500/30'
          : validPercentage >= 80
          ? 'bg-yellow-500/10 border-yellow-500/30'
          : 'bg-red-500/10 border-red-500/30'
      }`}>
        <h3 className="font-bold text-gray-300 mb-4">FINA Compliance Status</h3>
        <div className="space-y-3">
          <div className="text-center">
            <p className={`text-4xl font-bold ${
              validPercentage >= 95 ? 'text-green-400' :
              validPercentage >= 80 ? 'text-yellow-400' :
              'text-red-400'
            }`}>
              {validPercentage.toFixed(1)}%
            </p>
            <p className="text-sm text-gray-500 mt-1">Valid FINA Dives</p>
          </div>

          <div className="w-full bg-gray-700 rounded-full h-3">
            <div
              className={`h-3 rounded-full transition-all ${
                validPercentage >= 95 ? 'bg-green-500' :
                validPercentage >= 80 ? 'bg-yellow-500' :
                'bg-red-500'
              }`}
              style={{ width: `${validPercentage}%` }}
            ></div>
          </div>

          <div className="text-xs text-gray-500 text-center">
            {stats.valid_dives} of {stats.total_dives} dives valid
          </div>
        </div>
      </div>
    )
  }

  // Full dashboard
  return (
    <div className="space-y-6">
      {/* Overview */}
      <div className={`rounded-lg p-8 border ${
        validPercentage >= 95
          ? 'bg-green-500/10 border-green-500/30'
          : validPercentage >= 80
          ? 'bg-yellow-500/10 border-yellow-500/30'
          : 'bg-red-500/10 border-red-500/30'
      }`}>
        <div className="text-center space-y-4">
          <h2 className="text-3xl font-bold text-gray-300">FINA Compliance Dashboard</h2>
          <div className="text-6xl font-bold" style={{
            color: validPercentage >= 95 ? '#4ade80' : validPercentage >= 80 ? '#facc15' : '#f87171'
          }}>
            {validPercentage.toFixed(1)}%
          </div>
          <p className="text-xl text-gray-300">
            {stats.valid_dives} of {stats.total_dives} dives comply with FINA standards
          </p>
        </div>

        {/* Compliance Bar */}
        <div className="mt-6">
          <div className="w-full bg-gray-700 rounded-full h-4 overflow-hidden">
            <div
              className={`h-4 rounded-full transition-all ${
                validPercentage >= 95 ? 'bg-green-500' :
                validPercentage >= 80 ? 'bg-yellow-500' :
                'bg-red-500'
              }`}
              style={{ width: `${validPercentage}%` }}
            ></div>
          </div>
        </div>

        {/* Status Message */}
        <div className="mt-6 text-center">
          {validPercentage >= 95 && (
            <p className="text-green-400 font-semibold">
              ✅ Excellent compliance! All diving data meets FINA standards.
            </p>
          )}
          {validPercentage >= 80 && validPercentage < 95 && (
            <p className="text-yellow-400 font-semibold">
              ⚠️ Good compliance with minor issues. Review problematic dives below.
            </p>
          )}
          {validPercentage < 80 && (
            <p className="text-red-400 font-semibold">
              ❌ Significant compliance issues detected. Review and fix dives below.
            </p>
          )}
        </div>
      </div>

      {/* Statistics Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <p className="text-gray-500 text-sm mb-1">Total Dives</p>
          <p className="text-3xl font-bold text-cyan-400">{stats.total_dives}</p>
        </div>
        <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
          <p className="text-gray-500 text-sm mb-1">Valid Dives</p>
          <p className="text-3xl font-bold text-green-400">{stats.valid_dives}</p>
        </div>
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <p className="text-gray-500 text-sm mb-1">Invalid Dives</p>
          <p className="text-3xl font-bold text-red-400">{stats.invalid_dives}</p>
        </div>
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
          <p className="text-gray-500 text-sm mb-1">Compliance Score</p>
          <p className="text-3xl font-bold text-blue-400">{validPercentage.toFixed(0)}%</p>
        </div>
      </div>

      {/* By Height */}
      {Object.keys(stats.by_height).length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
          <button
            onClick={() => setExpandedSection(expandedSection === 'height' ? null : 'height')}
            className="w-full flex items-center justify-between hover:opacity-80 transition-opacity"
          >
            <h3 className="font-bold text-gray-300">Compliance by Height</h3>
            <span className="text-gray-500">{expandedSection === 'height' ? '▼' : '▶'}</span>
          </button>

          {expandedSection === 'height' && (
            <div className="mt-4 space-y-2">
              {Object.entries(stats.by_height).map(([height, data]) => {
                const heightTotal = data.valid + data.invalid
                const heightPercent = (data.valid / heightTotal) * 100

                return (
                  <div key={height} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-gray-300 font-semibold">{height}</span>
                      <span className={`text-sm font-bold ${
                        heightPercent >= 95 ? 'text-green-400' :
                        heightPercent >= 80 ? 'text-yellow-400' :
                        'text-red-400'
                      }`}>
                        {heightPercent.toFixed(0)}% ({data.valid}/{heightTotal})
                      </span>
                    </div>
                    <div className="w-full bg-gray-700 rounded-full h-2">
                      <div
                        className={`h-2 rounded-full ${
                          heightPercent >= 95 ? 'bg-green-500' :
                          heightPercent >= 80 ? 'bg-yellow-500' :
                          'bg-red-500'
                        }`}
                        style={{ width: `${heightPercent}%` }}
                      ></div>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* By Group */}
      {Object.keys(stats.by_group).length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-6">
          <button
            onClick={() => setExpandedSection(expandedSection === 'group' ? null : 'group')}
            className="w-full flex items-center justify-between hover:opacity-80 transition-opacity"
          >
            <h3 className="font-bold text-gray-300">Compliance by Dive Group</h3>
            <span className="text-gray-500">{expandedSection === 'group' ? '▼' : '▶'}</span>
          </button>

          {expandedSection === 'group' && (
            <div className="mt-4 grid grid-cols-2 md:grid-cols-3 gap-3">
              {Object.entries(stats.by_group).map(([group, data]) => {
                const groupTotal = data.valid + data.invalid
                const groupPercent = (data.valid / groupTotal) * 100

                return (
                  <div key={group} className="bg-gray-800/50 border border-gray-700 rounded p-3">
                    <p className="text-sm text-gray-400 mb-2">Group {group}</p>
                    <div className="w-full bg-gray-700 rounded-full h-2 mb-2">
                      <div
                        className={`h-2 rounded-full ${
                          groupPercent >= 95 ? 'bg-green-500' :
                          groupPercent >= 80 ? 'bg-yellow-500' :
                          'bg-red-500'
                        }`}
                        style={{ width: `${groupPercent}%` }}
                      ></div>
                    </div>
                    <p className={`text-xs font-bold ${
                      groupPercent >= 95 ? 'text-green-400' :
                      groupPercent >= 80 ? 'text-yellow-400' :
                      'text-red-400'
                    }`}>
                      {groupPercent.toFixed(0)}%
                    </p>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      )}

      {/* Problematic Dives */}
      {stats.problematic_dives.length > 0 && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-6">
          <button
            onClick={() => setExpandedSection(expandedSection === 'problems' ? null : 'problems')}
            className="w-full flex items-center justify-between hover:opacity-80 transition-opacity mb-4"
          >
            <h3 className="font-bold text-red-400">
              Issues Found ({stats.problematic_dives.length})
            </h3>
            <span className="text-gray-500">{expandedSection === 'problems' ? '▼' : '▶'}</span>
          </button>

          {expandedSection === 'problems' && (
            <div className="space-y-2">
              {stats.problematic_dives.map((dive) => (
                <div key={dive.id} className="bg-red-500/20 border border-red-500/30 rounded p-3">
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="font-semibold text-red-400">
                        {dive.dive_code} @ {dive.height}
                      </p>
                      <p className="text-sm text-red-300 mt-1">{dive.error}</p>
                    </div>
                    <span className="text-red-500 font-bold">✕</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Refresh */}
      <div className="text-center">
        <button
          onClick={fetchComplianceStats}
          className="px-4 py-2 bg-blue-500/30 hover:bg-blue-500/40 text-blue-400 rounded font-semibold transition-colors text-sm"
        >
          🔄 Refresh Compliance Status
        </button>
      </div>
    </div>
  )
}

export default ComplianceDashboard
