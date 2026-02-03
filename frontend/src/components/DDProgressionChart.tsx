import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface MonthlyDDData {
  month: string
  max_dd: number
  attempts: number
}

function DDProgressionChart() {
  const [data, setData] = useState<MonthlyDDData[]>([])
  const [loading, setLoading] = useState(true)
  const [currentMax, setCurrentMax] = useState(0)
  const [highestAchieved, setHighestAchieved] = useState(0)

  useEffect(() => {
    fetchDDProgression()
  }, [])

  const fetchDDProgression = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/journey')
      if (response.data.dd_progression) {
        setData(response.data.dd_progression.months || [])
        setCurrentMax(response.data.dd_progression.current_max)
        setHighestAchieved(response.data.dd_progression.highest_achieved)
      }
    } catch (err) {
      console.error('Error fetching DD progression:', err)
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return <div className="animate-pulse bg-gray-800 rounded-lg h-40 border border-gray-700"></div>
  }

  if (!data || data.length === 0) {
    return (
      <div className="bg-gray-800 rounded-lg p-6 border border-gray-700 text-center">
        <p className="text-gray-400">No DD progression data available yet</p>
      </div>
    )
  }

  // Find min and max for scaling
  const minDD = 1.0
  const maxDD = Math.max(...data.map(d => d.max_dd), 4.0)
  const range = maxDD - minDD

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <div className="mb-6">
        <h3 className="text-lg font-bold text-yellow-400 mb-2">Your DD Progression</h3>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          <div className="bg-gray-700 rounded p-2">
            <div className="text-gray-400">Current Max</div>
            <div className="text-xl font-bold text-yellow-400">{currentMax.toFixed(1)}</div>
          </div>
          <div className="bg-gray-700 rounded p-2">
            <div className="text-gray-400">Highest</div>
            <div className="text-xl font-bold text-orange-400">{highestAchieved.toFixed(1)}</div>
          </div>
          <div className="bg-gray-700 rounded p-2">
            <div className="text-gray-400">Months</div>
            <div className="text-xl font-bold text-cyan-400">{data.length}</div>
          </div>
        </div>
      </div>

      {/* Simple text-based chart */}
      <div className="space-y-2">
        {data.map((month, idx) => {
          const height = range > 0 ? ((month.max_dd - minDD) / range) * 100 : 0
          const colorClass =
            month.max_dd <= 1.8
              ? 'bg-green-500'
              : month.max_dd <= 2.5
                ? 'bg-yellow-500'
                : month.max_dd <= 3.3
                  ? 'bg-orange-500'
                  : 'bg-red-500'

          return (
            <div key={idx} className="flex items-center gap-3">
              <div className="w-20 text-sm font-medium text-gray-400 text-right truncate">
                {month.month}
              </div>
              <div className="flex-1">
                <div className="h-8 bg-gray-700 rounded relative overflow-hidden">
                  <div
                    className={`h-full ${colorClass} rounded flex items-center justify-end pr-2 transition-all`}
                    style={{ width: `${Math.max(height, 5)}%` }}
                  >
                    <span className="text-xs font-bold text-white">{month.max_dd.toFixed(1)}</span>
                  </div>
                </div>
              </div>
              <div className="w-16 text-right text-xs text-gray-400">
                {month.attempts} dives
              </div>
            </div>
          )
        })}
      </div>

      {/* Legend */}
      <div className="mt-6 pt-6 border-t border-gray-700 grid grid-cols-4 gap-2 text-xs">
        <div className="text-center">
          <div className="h-4 bg-green-500 rounded mb-1"></div>
          <div className="text-gray-400">Easy</div>
          <div className="text-gray-500">1.2-1.8</div>
        </div>
        <div className="text-center">
          <div className="h-4 bg-yellow-500 rounded mb-1"></div>
          <div className="text-gray-400">Medium</div>
          <div className="text-gray-500">1.9-2.5</div>
        </div>
        <div className="text-center">
          <div className="h-4 bg-orange-500 rounded mb-1"></div>
          <div className="text-gray-400">Hard</div>
          <div className="text-gray-500">2.6-3.3</div>
        </div>
        <div className="text-center">
          <div className="h-4 bg-red-500 rounded mb-1"></div>
          <div className="text-gray-400">Expert</div>
          <div className="text-gray-500">3.4-4.1</div>
        </div>
      </div>
    </div>
  )
}

export default DDProgressionChart
