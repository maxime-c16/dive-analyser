import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import { useSyncStatus } from '../hooks/useSyncStatus'
import SyncStatus from '../components/SyncStatus'
import DDProgressionChart from '../components/DDProgressionChart'
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from 'recharts'
import { format, parseISO } from 'date-fns'

interface OverallStats {
  total_dives: number
  avg_performance: number
  success_rate: number
  total_sessions: number
  avg_dd?: number
  max_dd?: number
}

interface MonthlyStats {
  month: string
  total_dives: number
  avg_performance: number
  success_rate: number
}

interface HeightStats {
  [key: string]: {
    total_dives: number
    avg_performance: number
    success_rate: number
  }
}

interface DirectionStats {
  [key: string]: {
    total_dives: number
    avg_performance: number
    success_rate: number
  }
}

interface RecentSession {
  id: number
  date: string
  total_dives: number
  total_personal_dives: number
  avg_performance: number | null
  success_rate: number | null
}

const COLORS = {
  primary: '#06b6d4',    // cyan-500
  success: '#22c55e',    // green-500
  warning: '#f59e0b',    // amber-500
  danger: '#ef4444',     // red-500
  purple: '#a855f7',     // purple-500
  pink: '#ec4899',       // pink-500
}

const DIRECTION_NAMES: { [key: string]: string } = {
  '1': 'Forward',
  '2': 'Back',
  '3': 'Reverse',
  '4': 'Inward',
  '5': 'Twist',
}

const PERFORMANCE_COLORS = {
  P: '#22c55e',
  G: '#3b82f6',
  M: '#f59e0b',
  B: '#f97316',
  F: '#ef4444',
}

function Dashboard() {
  const { currentSync, isConnected } = useSyncStatus()
  const [stats, setStats] = useState<OverallStats | null>(null)
  const [monthlyStats, setMonthlyStats] = useState<MonthlyStats[]>([])
  const [heightStats, setHeightStats] = useState<HeightStats>({})
  const [directionStats, setDirectionStats] = useState<DirectionStats>({})
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true)
        const [overallRes, monthlyRes, heightRes, directionRes, sessionsRes] = await Promise.all([
          api.get('/api/v1/analytics/overall'),
          api.get('/api/v1/analytics/monthly'),
          api.get('/api/v1/analytics/by-height'),
          api.get('/api/v1/analytics/by-direction'),
          api.get('/api/v1/sessions?limit=5'),
        ])
        setStats(overallRes.data)
        setMonthlyStats(monthlyRes.data)
        setHeightStats(heightRes.data)
        setDirectionStats(directionRes.data)
        setRecentSessions(sessionsRes.data)
        setError(null)
      } catch (err) {
        console.error('Error fetching data:', err)
        setError('Failed to load dashboard data')
      } finally {
        setLoading(false)
      }
    }
    fetchData()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-cyan-500 border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-xl text-gray-400">Loading your diving data...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="text-center">
          <p className="text-2xl text-red-500 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="bg-cyan-600 hover:bg-cyan-700 px-6 py-2 rounded-lg"
          >
            Retry
          </button>
        </div>
      </div>
    )
  }

  // Prepare chart data
  const heightChartData = Object.entries(heightStats).map(([height, data]) => ({
    name: height,
    dives: data.total_dives,
    performance: data.avg_performance,
    successRate: data.success_rate,
  })).sort((a, b) => {
    const order = ['1M', '3M', '5M', '7M', '10M']
    return order.indexOf(a.name) - order.indexOf(b.name)
  })

  const directionChartData = Object.entries(directionStats).map(([dir, data]) => ({
    name: DIRECTION_NAMES[dir] || `Dir ${dir}`,
    dives: data.total_dives,
    performance: data.avg_performance,
    successRate: data.success_rate,
  }))

  const monthlyChartData = monthlyStats.map(m => ({
    ...m,
    monthLabel: format(parseISO(m.month + '-01'), 'MMM yy'),
  }))

  // Performance distribution for pie chart
  const performanceLabels = ['Perfect', 'Good', 'Medium', 'Bad', 'Failed']
  const performanceData = [
    { name: 'Perfect', value: Math.round((stats?.success_rate || 0) * 0.3), color: PERFORMANCE_COLORS.P },
    { name: 'Good', value: Math.round((stats?.success_rate || 0) * 0.7 - 20), color: PERFORMANCE_COLORS.G },
    { name: 'Medium', value: Math.round(100 - (stats?.success_rate || 0) - 5), color: PERFORMANCE_COLORS.M },
    { name: 'Bad/Failed', value: 5, color: PERFORMANCE_COLORS.F },
  ].filter(d => d.value > 0)

  return (
    <div className="p-4 md:p-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold text-white">Training Dashboard</h1>
          <p className="text-gray-400 mt-1 text-sm md:text-base">Your diving performance at a glance</p>
        </div>
        <div className="flex flex-col items-start md:items-end gap-2 text-xs md:text-sm text-gray-500">
          <div>Last updated: {format(new Date(), 'PPp')}</div>
          {currentSync && (
            <div className="text-cyan-400">
              Sync: {currentSync.progress_percent}%
            </div>
          )}
        </div>
      </div>

      {/* Sync Status Panel - Mobile View */}
      {currentSync && (
        <div className="lg:hidden">
          <SyncStatus compact={false} />
        </div>
      )}

      {/* Key Metrics */}
      <div className="grid grid-cols-2 md:grid-cols-2 lg:grid-cols-5 gap-2 md:gap-4">
        <MetricCard
          title="Total Dives"
          value={stats?.total_dives || 0}
          subtitle="Personal attempts"
          color="cyan"
          icon="🏊"
        />
        <MetricCard
          title="Success Rate"
          value={`${stats?.success_rate?.toFixed(1) || 0}%`}
          subtitle="Medium or better"
          color="green"
          trend={stats?.success_rate && stats.success_rate > 75 ? 'up' : 'neutral'}
          icon="🎯"
        />
        <MetricCard
          title="Avg Performance"
          value={stats?.avg_performance?.toFixed(2) || '0.00'}
          subtitle="Out of 4.0"
          color="purple"
          icon="📊"
        />
        {stats?.avg_dd !== undefined && stats.avg_dd > 0 && (
          <MetricCard
            title="Avg DD"
            value={stats.avg_dd.toFixed(1)}
            subtitle="Difficulty degree"
            color="yellow"
            icon="⚡"
          />
        )}
        {stats?.max_dd !== undefined && stats.max_dd > 0 && (
          <MetricCard
            title="Max DD"
            value={stats.max_dd.toFixed(1)}
            subtitle="Highest difficulty"
            color="orange"
            icon="🔥"
          />
        )}
        <MetricCard
          title="Training Sessions"
          value={stats?.total_sessions || 0}
          subtitle="Total days"
          color="amber"
          icon="📅"
        />
      </div>

      {/* DD Progression */}
      <div className="w-full">
        <DDProgressionChart />
      </div>

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Monthly Progression */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold text-white mb-4">Monthly Progression</h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={monthlyChartData}>
              <defs>
                <linearGradient id="colorDives" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS.primary} stopOpacity={0.3}/>
                  <stop offset="95%" stopColor={COLORS.primary} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="monthLabel" stroke="#9ca3af" fontSize={12} />
              <YAxis stroke="#9ca3af" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                labelStyle={{ color: '#fff' }}
              />
              <Area
                type="monotone"
                dataKey="total_dives"
                stroke={COLORS.primary}
                fillOpacity={1}
                fill="url(#colorDives)"
                name="Dives"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Performance by Height */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold text-white mb-4">Performance by Height</h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={heightChartData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis type="number" stroke="#9ca3af" fontSize={12} domain={[0, 4]} />
              <YAxis dataKey="name" type="category" stroke="#9ca3af" fontSize={12} width={40} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                labelStyle={{ color: '#fff' }}
                formatter={(value: number, name: string) => [
                  name === 'performance' ? value.toFixed(2) : value,
                  name === 'performance' ? 'Avg Performance' : name === 'dives' ? 'Total Dives' : name
                ]}
              />
              <Bar dataKey="performance" fill={COLORS.primary} radius={[0, 4, 4, 0]} name="Avg Performance" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Direction Breakdown */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold text-white mb-4">By Direction</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={directionChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="name" stroke="#9ca3af" fontSize={11} angle={-20} textAnchor="end" height={50} />
              <YAxis stroke="#9ca3af" fontSize={12} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                labelStyle={{ color: '#fff' }}
              />
              <Bar dataKey="dives" fill={COLORS.purple} radius={[4, 4, 0, 0]} name="Dives" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Success Rate Trend */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold text-white mb-4">Success Rate Trend</h2>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={monthlyChartData}>
              <defs>
                <linearGradient id="colorSuccess" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor={COLORS.success} stopOpacity={0.3}/>
                  <stop offset="95%" stopColor={COLORS.success} stopOpacity={0}/>
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#374151" />
              <XAxis dataKey="monthLabel" stroke="#9ca3af" fontSize={11} />
              <YAxis stroke="#9ca3af" fontSize={12} domain={[0, 100]} />
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
                formatter={(value: number) => [`${value.toFixed(1)}%`, 'Success Rate']}
              />
              <Area
                type="monotone"
                dataKey="success_rate"
                stroke={COLORS.success}
                fillOpacity={1}
                fill="url(#colorSuccess)"
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Height Distribution Pie */}
        <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
          <h2 className="text-xl font-semibold text-white mb-4">Training Focus</h2>
          <ResponsiveContainer width="100%" height={240}>
            <PieChart>
              <Pie
                data={heightChartData}
                cx="50%"
                cy="50%"
                innerRadius={50}
                outerRadius={80}
                fill="#8884d8"
                paddingAngle={2}
                dataKey="dives"
                label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                labelLine={false}
              >
                {heightChartData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={Object.values(COLORS)[index % Object.values(COLORS).length]} />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{ backgroundColor: '#1f2937', border: '1px solid #374151', borderRadius: '8px' }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Sessions */}
      <div className="bg-gray-800 rounded-xl p-6 border border-gray-700">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xl font-semibold text-white">Recent Training Sessions</h2>
          <a href="/sessions" className="text-cyan-400 hover:text-cyan-300 text-sm">View all →</a>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="text-gray-400 text-sm border-b border-gray-700">
                <th className="pb-3 font-medium">Date</th>
                <th className="pb-3 font-medium">Dives</th>
                <th className="pb-3 font-medium">Personal</th>
                <th className="pb-3 font-medium">Avg Performance</th>
                <th className="pb-3 font-medium">Success Rate</th>
              </tr>
            </thead>
            <tbody>
              {recentSessions.map((session) => (
                <tr key={session.id} className="border-b border-gray-700/50 hover:bg-gray-700/30">
                  <td className="py-3 text-white font-medium">
                    {format(parseISO(session.date), 'MMM d, yyyy')}
                  </td>
                  <td className="py-3 text-gray-300">{session.total_dives}</td>
                  <td className="py-3 text-gray-300">{session.total_personal_dives}</td>
                  <td className="py-3">
                    <PerformanceBadge value={session.avg_performance} />
                  </td>
                  <td className="py-3">
                    <SuccessRateBadge value={session.success_rate} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

// Helper Components
function MetricCard({ title, value, subtitle, color, trend, icon }: {
  title: string
  value: string | number
  subtitle: string
  color: 'cyan' | 'green' | 'purple' | 'amber' | 'yellow' | 'orange'
  trend?: 'up' | 'down' | 'neutral'
  icon: string
}) {
  const colorClasses = {
    cyan: 'border-cyan-500/30 bg-cyan-500/5',
    green: 'border-green-500/30 bg-green-500/5',
    purple: 'border-purple-500/30 bg-purple-500/5',
    amber: 'border-amber-500/30 bg-amber-500/5',
    yellow: 'border-yellow-500/30 bg-yellow-500/5',
    orange: 'border-orange-500/30 bg-orange-500/5',
  }
  const valueColors = {
    cyan: 'text-cyan-400',
    green: 'text-green-400',
    purple: 'text-purple-400',
    amber: 'text-amber-400',
    yellow: 'text-yellow-400',
    orange: 'text-orange-400',
  }

  return (
    <div className={`rounded-xl p-5 border ${colorClasses[color]} transition hover:scale-[1.02]`}>
      <div className="flex items-start justify-between">
        <div>
          <p className="text-gray-400 text-sm font-medium">{title}</p>
          <p className={`text-3xl font-bold mt-1 ${valueColors[color]}`}>{value}</p>
          <p className="text-gray-500 text-xs mt-1">{subtitle}</p>
        </div>
        <span className="text-2xl">{icon}</span>
      </div>
    </div>
  )
}

function PerformanceBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-gray-500">-</span>

  const color = value >= 3 ? 'text-green-400' : value >= 2 ? 'text-amber-400' : 'text-red-400'
  return <span className={`font-medium ${color}`}>{value.toFixed(2)}</span>
}

function SuccessRateBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-gray-500">-</span>

  const color = value >= 80 ? 'bg-green-500/20 text-green-400' :
                value >= 60 ? 'bg-amber-500/20 text-amber-400' :
                'bg-red-500/20 text-red-400'
  return (
    <span className={`px-2 py-1 rounded text-sm font-medium ${color}`}>
      {value.toFixed(1)}%
    </span>
  )
}

export default Dashboard
