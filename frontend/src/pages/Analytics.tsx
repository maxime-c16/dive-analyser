import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import {
  AreaChart, Area, BarChart, Bar, LineChart, Line, RadarChart, Radar,
  PolarGrid, PolarAngleAxis, PolarRadiusAxis, ComposedChart,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, Cell
} from 'recharts'
import { format, parseISO } from 'date-fns'

interface MonthlyStats {
  month: string
  total_dives: number
  avg_performance: number
  success_rate: number
  average_dd?: number | null
  dd_coverage_rate?: number | null
}

interface HeightStats {
  [key: string]: {
    total_dives: number
    avg_performance: number
    success_rate: number
    average_dd?: number | null
    dd_coverage_rate?: number | null
  }
}

interface DirectionStats {
  [key: string]: {
    total_dives: number
    avg_performance: number
    success_rate: number
    average_dd?: number | null
    dd_coverage_rate?: number | null
  }
}

interface TrendingDive {
  dive_code: string
  improvement: number
  recent_avg: number
  total_attempts: number
}

const COLORS = {
  primary: '#06b6d4',
  success: '#22c55e',
  warning: '#f59e0b',
  danger: '#ef4444',
  purple: '#a855f7',
  pink: '#ec4899',
  blue: '#3b82f6',
}

const DIRECTION_NAMES: { [key: string]: string } = {
  '1': 'Forward',
  '2': 'Back',
  '3': 'Reverse',
  '4': 'Inward',
  '5': 'Twist',
}

const HEIGHT_COLORS: { [key: string]: string } = {
  '1M': '#06b6d4',
  '3M': '#22c55e',
  '5M': '#f59e0b',
  '7M': '#a855f7',
  '10M': '#ef4444',
}

function Analytics() {
  const [monthlyStats, setMonthlyStats] = useState<MonthlyStats[]>([])
  const [heightStats, setHeightStats] = useState<HeightStats>({})
  const [directionStats, setDirectionStats] = useState<DirectionStats>({})
  const [trendingDives, setTrendingDives] = useState<TrendingDive[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        const [monthlyRes, heightRes, directionRes, trendingRes] = await Promise.all([
          api.get('/api/v1/analytics/monthly'),
          api.get('/api/v1/analytics/by-height'),
          api.get('/api/v1/analytics/by-direction'),
          api.get('/api/v1/analytics/trending?limit=10'),
        ])
        setMonthlyStats(monthlyRes.data)
        setHeightStats(heightRes.data)
        setDirectionStats(directionRes.data)
        setTrendingDives(trendingRes.data)
      } catch (err) {
        console.error('Error fetching analytics:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="w-16 h-16 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin"></div>
      </div>
    )
  }

  // Prepare chart data
  const heightChartData = Object.entries(heightStats).map(([height, data]) => ({
    name: height,
    dives: data.total_dives,
    performance: data.avg_performance,
    averageDd: data.average_dd,
    ddCoverage: data.dd_coverage_rate,
    successRate: data.success_rate,
  })).sort((a, b) => {
    const order = ['1M', '3M', '5M', '7M', '10M']
    return order.indexOf(a.name) - order.indexOf(b.name)
  })

  const directionChartData = Object.entries(directionStats).map(([dir, data]) => ({
    name: DIRECTION_NAMES[dir] || `Dir ${dir}`,
    fullMark: 4,
    dives: data.total_dives,
    performance: data.avg_performance,
    averageDd: data.average_dd,
    ddCoverage: data.dd_coverage_rate,
    successRate: data.success_rate,
  }))

  const monthlyChartData = monthlyStats.map(m => ({
    ...m,
    monthLabel: format(parseISO(m.month + '-01'), 'MMM yy'),
  }))
  const performanceKey = 'avg_performance'
  const performanceName = 'Average execution /10'
  const groupPerformanceKey = 'performance'

  // Calculate averages for comparison
  const avgPerformance = monthlyChartData.reduce((acc, m) => acc + m.avg_performance, 0) / monthlyChartData.length || 0
  const avgSuccessRate = monthlyChartData.reduce((acc, m) => acc + m.success_rate, 0) / monthlyChartData.length || 0

  return (
    <div className="app-page">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-white">Detailed Analytics</h1>
        <p className="text-gray-400 mt-1">Deep dive into your performance metrics</p>
      </div>

      {/* Performance Over Time */}
      <div className="app-panel">
        <div className="mb-4"><h2 className="text-xl font-semibold text-white">Performance Over Time</h2><p className="mt-1 text-sm text-gray-400">Execution remains on its calibrated 0–10 scale. Difficulty is shown separately as official DD context.</p></div>
        <div className="app-chart"><ResponsiveContainer width="100%" height={300}>
          <ComposedChart data={monthlyChartData}>
            <defs>
              <linearGradient id="colorPerf" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor={COLORS.primary} stopOpacity={0.3}/>
                <stop offset="95%" stopColor={COLORS.primary} stopOpacity={0}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
            <XAxis dataKey="monthLabel" stroke="#9ca3af" />
            <YAxis yAxisId="left" stroke="#9ca3af" domain={[0, 10]} />
            <YAxis yAxisId="right" orientation="right" stroke="#9ca3af" domain={[0, 100]} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              labelStyle={{ color: '#fff' }}
            />
            <Legend />
            <Area
              yAxisId="left"
              type="monotone"
              dataKey={performanceKey}
              stroke={COLORS.primary}
              fill="url(#colorPerf)"
              name={performanceName}
            />
            <Line
              yAxisId="right"
              type="monotone"
              dataKey="success_rate"
              stroke={COLORS.success}
              strokeWidth={2}
              dot={{ fill: COLORS.success }}
              name="Success Rate %"
            />
          </ComposedChart>
        </ResponsiveContainer></div>
      </div>

      {/* Height Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-white mb-1">Performance by Height</h2><p className="mb-4 text-sm text-gray-400">{performanceName}; tooltip includes average DD and coverage.</p>
          <div className="app-chart"><ResponsiveContainer width="100%" height={280}>
            <BarChart data={heightChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" stroke="#9ca3af" />
              <YAxis stroke="#9ca3af" domain={[0, 10]} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                formatter={(value: number) => value.toFixed(2)}
              />
              <Legend />
              <Bar dataKey={groupPerformanceKey} name={performanceName} radius={[4, 4, 0, 0]}>
                {heightChartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={HEIGHT_COLORS[entry.name] || COLORS.primary} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer></div>
        </div>

        <div className="app-panel">
          <h2 className="text-xl font-semibold text-white mb-4">Success Rate by Height</h2>
          <div className="app-chart"><ResponsiveContainer width="100%" height={280}>
            <BarChart data={heightChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" stroke="#9ca3af" />
              <YAxis stroke="#9ca3af" domain={[0, 100]} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                formatter={(value: number) => `${value.toFixed(1)}%`}
              />
              <Legend />
              <Bar dataKey="successRate" name="Success Rate %" radius={[4, 4, 0, 0]}>
                {heightChartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.successRate >= 80 ? COLORS.success : entry.successRate >= 60 ? COLORS.warning : COLORS.danger}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer></div>
        </div>
      </div>

      {/* Direction Analysis */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-white mb-1">Direction comparison</h2><p className="mb-4 text-sm text-gray-400">{performanceName}</p>
          <div className="app-chart"><ResponsiveContainer width="100%" height={300}>
            <RadarChart cx="50%" cy="50%" outerRadius="80%" data={directionChartData}>
              <PolarGrid stroke="#374151" />
              <PolarAngleAxis dataKey="name" stroke="#9ca3af" />
              <PolarRadiusAxis angle={30} domain={[0, 10]} stroke="#9ca3af" />
              <Radar
                name={performanceName}
                dataKey={groupPerformanceKey}
                stroke={COLORS.primary}
                fill={COLORS.primary}
                fillOpacity={0.5}
              />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              />
              <Legend />
            </RadarChart>
          </ResponsiveContainer></div>
        </div>

        <div className="app-panel">
          <h2 className="text-xl font-semibold text-white mb-4">Volume by Direction</h2>
          <div className="app-chart"><ResponsiveContainer width="100%" height={300}>
            <BarChart data={directionChartData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis type="number" stroke="#9ca3af" />
              <YAxis dataKey="name" type="category" stroke="#9ca3af" width={70} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              />
              <Bar dataKey="dives" fill={COLORS.purple} radius={[0, 4, 4, 0]} name="Total Dives" />
            </BarChart>
          </ResponsiveContainer></div>
        </div>
      </div>

      {/* Trending Dives */}
      <div className="app-panel">
        <h2 className="text-xl font-semibold text-white mb-4">Trending Dives (Biggest Improvements)</h2>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-5">
          {trendingDives.slice(0, 5).map((dive, index) => (
            <div
              key={dive.dive_code}
              className={`min-w-0 border p-4 ${
                dive.improvement > 0
                  ? 'border-green-500/30 bg-green-500/5'
                  : 'border-red-500/30 bg-red-500/5'
              }`}
            >
              <div className="flex items-center justify-between mb-2">
                <span className="text-2xl font-bold text-white">{dive.dive_code}</span>
                <span className={`text-sm font-medium ${dive.improvement > 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {dive.improvement > 0 ? '↑' : '↓'} {Math.abs(dive.improvement).toFixed(2)}
                </span>
              </div>
              <div className="space-y-1 text-sm">
                <div className="flex justify-between text-gray-400">
                  <span>Recent Avg:</span>
                  <span className="text-white">{dive.recent_avg.toFixed(2)}</span>
                </div>
                <div className="flex justify-between text-gray-400">
                  <span>Attempts:</span>
                  <span className="text-white">{dive.total_attempts}</span>
                </div>
              </div>
            </div>
          ))}
        </div>
        {trendingDives.length === 0 && (
          <p className="text-gray-500 text-center py-8">Not enough data to show trends yet</p>
        )}
      </div>

      {/* Stats Summary */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div className="app-panel">
          <h3 className="text-gray-400 text-sm mb-1">Average Performance</h3>
          <p className="text-3xl font-bold text-cyan-400">{avgPerformance.toFixed(2)}</p>
          <p className="text-gray-500 text-sm mt-1">Calibrated 0-10 scale</p>
        </div>
        <div className="app-panel">
          <h3 className="text-gray-400 text-sm mb-1">Average Success Rate</h3>
          <p className="text-3xl font-bold text-green-400">{avgSuccessRate.toFixed(1)}%</p>
          <p className="text-gray-500 text-sm mt-1">Medium or better</p>
        </div>
        <div className="app-panel">
          <h3 className="text-gray-400 text-sm mb-1">Heights Trained</h3>
          <p className="text-3xl font-bold text-purple-400">{Object.keys(heightStats).length}</p>
          <p className="text-gray-500 text-sm mt-1">Different platforms</p>
        </div>
      </div>
    </div>
  )
}

export default Analytics
