import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface DiveCodeStructure {
  group: number
  direction: number
  rotations: number
  twists: number
  position: string
  is_twisting: boolean
  is_flying: boolean
  is_armstand: boolean
}

interface DiveCodeData {
  code: string
  official_name: string
  description: string
  structure: DiveCodeStructure
  valid_heights: string[]
  dd_values: { [key: string]: number }
  is_valid: boolean
  errors: string[]
}

interface DiveCodeInfoProps {
  diveCode: string
  height?: string
}

function DiveCodeInfo({ diveCode, height }: DiveCodeInfoProps) {
  const [diveInfo, setDiveInfo] = useState<DiveCodeData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (diveCode) {
      fetchDiveInfo()
    }
  }, [diveCode])

  const fetchDiveInfo = async () => {
    if (!diveCode) return

    try {
      setLoading(true)
      const response = await api.get(
        `/api/v1/dive-codes/validate?code=${encodeURIComponent(diveCode)}`
      )
      setDiveInfo(response.data)
      setError(null)
    } catch (err) {
      console.error('Error fetching dive info:', err)
      setError(`Unable to fetch information for dive code: ${diveCode}`)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="animate-pulse bg-gray-700 h-24 rounded-lg"></div>
  }

  if (error) {
    return (
      <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
        <p className="text-red-400 text-sm">{error}</p>
      </div>
    )
  }

  if (!diveInfo) {
    return (
      <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-3">
        <p className="text-gray-400 text-sm">No information available</p>
      </div>
    )
  }

  const { structure, official_name, description, valid_heights, dd_values, is_valid } = diveInfo
  const selectedDDValue = height ? dd_values[height] : null

  // Difficulty level based on DD
  const getDifficultyLevel = (dd: number): string => {
    if (dd < 1.5) return 'Easy'
    if (dd < 2.5) return 'Moderate'
    if (dd < 3.5) return 'Difficult'
    if (dd < 4.5) return 'Very Difficult'
    return 'Elite'
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

  return (
    <div className="space-y-4">
      {/* Validity Badge */}
      <div className={`rounded-lg p-4 border ${is_valid ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
        <div className="flex items-start justify-between">
          <div>
            <p className={`font-bold ${is_valid ? 'text-green-400' : 'text-red-400'}`}>
              {is_valid ? '✅ Valid FINA Dive Code' : '❌ Invalid Dive Code'}
            </p>
            <p className="text-sm text-gray-300 mt-1">{official_name}</p>
          </div>
          {selectedDDValue && (
            <div className={`text-center px-4 py-2 rounded ${getDifficultyBgColor(selectedDDValue)} border`}>
              <p className={`font-bold text-lg ${getDifficultyColor(selectedDDValue)}`}>
                {selectedDDValue.toFixed(1)}
              </p>
              <p className={`text-xs font-semibold ${getDifficultyColor(selectedDDValue)}`}>
                DD @ {height}
              </p>
            </div>
          )}
        </div>
      </div>

      {/* Description */}
      {description && (
        <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4">
          <p className="text-gray-300 text-sm leading-relaxed">{description}</p>
        </div>
      )}

      {/* Structure Breakdown */}
      <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
        <h4 className="font-bold text-gray-300 mb-3">🔍 Dive Structure</h4>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Group</p>
            <p className="text-lg font-bold text-cyan-400">{structure.group}</p>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Direction</p>
            <p className="text-lg font-bold text-cyan-400">{structure.direction}</p>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Rotations</p>
            <p className="text-lg font-bold text-cyan-400">{structure.rotations}</p>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Twists</p>
            <p className="text-lg font-bold text-cyan-400">{structure.twists}</p>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Position</p>
            <p className="text-lg font-bold text-cyan-400">{structure.position}</p>
          </div>
          <div className="bg-gray-800/50 rounded p-2">
            <p className="text-xs text-gray-500 mb-1">Type</p>
            <p className="text-sm text-cyan-400 font-semibold">
              {structure.is_twisting ? '🔄 Twisting' : structure.is_flying ? '✈️ Flying' : structure.is_armstand ? '🤸 Armstand' : 'Standard'}
            </p>
          </div>
        </div>
      </div>

      {/* DD Values by Height */}
      {Object.keys(dd_values).length > 0 && (
        <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <h4 className="font-bold text-gray-300 mb-3">📊 Difficulty by Height</h4>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-2">
            {Object.entries(dd_values)
              .sort(([h1], [h2]) => {
                // Sort heights in standard order
                const order = ['1m', '3m', '5m', '7.5m', '10m', '5m platform', '7.5m platform', '10m platform']
                return order.indexOf(h1) - order.indexOf(h2)
              })
              .map(([h, dd]) => (
                <div
                  key={h}
                  className={`rounded p-3 border text-center ${
                    height === h ? 'bg-cyan-500/20 border-cyan-500/50' : 'bg-gray-800/50 border-gray-700'
                  }`}
                >
                  <p className="text-xs text-gray-500 mb-1">{h}</p>
                  <p className={`text-xl font-bold ${getDifficultyColor(dd)}`}>
                    {dd.toFixed(1)}
                  </p>
                  <p className={`text-xs font-semibold ${getDifficultyColor(dd)}`}>
                    {getDifficultyLevel(dd)}
                  </p>
                </div>
              ))}
          </div>
        </div>
      )}

      {/* Valid Heights */}
      {valid_heights.length > 0 && (
        <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-4">
          <p className="text-xs text-gray-500 mb-2 font-semibold uppercase">Valid at these heights</p>
          <div className="flex flex-wrap gap-2">
            {valid_heights.map((h) => (
              <span
                key={h}
                className={`px-3 py-1 rounded-full text-sm font-semibold ${
                  height === h
                    ? 'bg-cyan-500/50 text-cyan-400 border border-cyan-500'
                    : 'bg-blue-500/30 text-blue-400 border border-blue-500/50'
                }`}
              >
                {h}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Errors */}
      {!is_valid && diveInfo.errors.length > 0 && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4">
          <p className="text-xs text-gray-500 mb-2 font-semibold uppercase">Validation Issues</p>
          <ul className="space-y-1">
            {diveInfo.errors.map((error, idx) => (
              <li key={idx} className="text-red-400 text-sm">
                • {error}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default DiveCodeInfo
