import React, { useEffect, useState } from "react";
import { getNavigationData } from "../services/navigationData";
import { useSyncStatus } from "../hooks/useSyncStatus";
import SyncStatus from "../components/SyncStatus";
import DDProgressionChart from "../components/DDProgressionChart";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { format, parseISO } from "date-fns";
import {
  BarChart3,
  CalendarDays,
  Flame,
  Scale,
  Target,
  Waves,
  Zap,
  type LucideIcon,
} from "lucide-react";
import {
  getRecentPersonalDiveValues,
  type PersonalDiveValue,
} from "../services/personalDiveValueApi";

interface OverallStats {
  total_dives: number;
  avg_performance: number;
  success_rate: number;
  total_sessions: number;
  avg_dd?: number;
  max_dd?: number;
  dd_coverage_rate?: number | null;
}

interface MonthlyStats {
  month: string;
  total_dives: number;
  avg_performance: number;
  success_rate: number;
}

interface HeightStats {
  [key: string]: {
    total_dives: number;
    avg_performance: number;
    success_rate: number;
  };
}

interface DirectionStats {
  [key: string]: {
    total_dives: number;
    avg_performance: number;
    success_rate: number;
  };
}

interface RecentSession {
  id: number;
  date: string;
  total_dives: number;
  total_personal_dives: number;
  avg_performance: number | null;
  success_rate: number | null;
}

const COLORS = {
  primary: "#54beab", // app accent
  success: "#22c55e", // green-500
  warning: "#f59e0b", // amber-500
  danger: "#ef4444", // red-500
  purple: "#a855f7", // purple-500
  pink: "#ec4899", // pink-500
};

const DIRECTION_NAMES: { [key: string]: string } = {
  "1": "Forward",
  "2": "Back",
  "3": "Reverse",
  "4": "Inward",
  "5": "Twist",
};

const PERFORMANCE_COLORS = {
  P: "#22c55e",
  G: "#3b82f6",
  M: "#f59e0b",
  B: "#f97316",
  F: "#ef4444",
};

function Dashboard() {
  const { currentSync, isConnected } = useSyncStatus();
  const [stats, setStats] = useState<OverallStats | null>(null);
  const [monthlyStats, setMonthlyStats] = useState<MonthlyStats[]>([]);
  const [heightStats, setHeightStats] = useState<HeightStats>({});
  const [directionStats, setDirectionStats] = useState<DirectionStats>({});
  const [recentSessions, setRecentSessions] = useState<RecentSession[]>([]);
  const [personalValues, setPersonalValues] = useState<
    Array<PersonalDiveValue & { dive_code: string; dive_datetime: string }>
  >([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);
        const [
          overallRes,
          monthlyRes,
          heightRes,
          directionRes,
          sessionsRes,
          personalResult,
        ] = await Promise.all([
          getNavigationData("/api/v1/analytics/overall"),
          getNavigationData("/api/v1/analytics/monthly"),
          getNavigationData("/api/v1/analytics/by-height"),
          getNavigationData("/api/v1/analytics/by-direction"),
          getNavigationData("/api/v1/sessions?limit=100"),
          getRecentPersonalDiveValues(60).catch(() => ({
            version: "v1",
            values: [],
          })),
        ]);
        setStats(overallRes.data);
        setMonthlyStats(monthlyRes.data);
        setHeightStats(heightRes.data);
        setDirectionStats(directionRes.data);
        setRecentSessions(sessionsRes.data);
        setPersonalValues(personalResult.values);
        setError(null);
      } catch (err) {
        console.error("Error fetching data:", err);
        setError("Failed to load dashboard data");
      } finally {
        setLoading(false);
      }
    };
    fetchData();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="text-center">
          <div className="w-16 h-16 border-4 border-app-accent border-t-transparent rounded-full animate-spin mx-auto mb-4"></div>
          <p className="text-xl text-app-muted">Loading…</p>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-[80vh]">
        <div className="text-center">
          <p className="text-2xl text-red-400 mb-4">{error}</p>
          <button
            onClick={() => window.location.reload()}
            className="border border-app-accent bg-app-accent px-6 py-2 font-medium text-app-bg transition-colors hover:brightness-110"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  // Prepare chart data
  const heightChartData = Object.entries(heightStats)
    .map(([height, data]) => ({
      name: height,
      dives: data.total_dives,
      performance: data.avg_performance,
      successRate: data.success_rate,
    }))
    .sort((a, b) => {
      const order = ["1M", "3M", "5M", "7M", "10M"];
      return order.indexOf(a.name) - order.indexOf(b.name);
    });

  const directionChartData = Object.entries(directionStats).map(
    ([dir, data]) => ({
      name: DIRECTION_NAMES[dir] || `Dir ${dir}`,
      dives: data.total_dives,
      performance: data.avg_performance,
      successRate: data.success_rate,
    }),
  );

  const monthlyChartData = monthlyStats.map((m) => ({
    ...m,
    monthLabel: format(parseISO(m.month + "-01"), "MMM yy"),
  }));
  const personalValueChartData = personalValues
    .filter((value) => value.value != null)
    .map((value) => ({
      ...value,
      dateLabel: format(parseISO(value.dive_datetime), "d MMM"),
      personalValue: value.value,
    }));

  // Approximate tag distribution until the API exposes raw performance buckets.
  const performanceData = [
    {
      name: "Perfect",
      value: Math.round((stats?.success_rate || 0) * 0.3),
      color: PERFORMANCE_COLORS.P,
    },
    {
      name: "Good",
      value: Math.round((stats?.success_rate || 0) * 0.7 - 20),
      color: PERFORMANCE_COLORS.G,
    },
    {
      name: "Medium",
      value: Math.round(100 - (stats?.success_rate || 0) - 5),
      color: PERFORMANCE_COLORS.M,
    },
    { name: "Bad/Failed", value: 5, color: PERFORMANCE_COLORS.F },
  ].filter((d) => d.value > 0);

  return (
    <div className="app-page">
      {/* Header */}
      <div className="flex flex-col md:flex-row items-start md:items-center justify-between gap-4">
        <h1 className="text-2xl md:text-3xl font-bold text-app-text">
          Training Dashboard
        </h1>
        <div className="flex flex-col items-start md:items-end gap-2 text-xs md:text-sm text-app-muted">
          <div>Last updated: {format(new Date(), "PPp")}</div>
          {currentSync && (
            <div className="text-app-accent">
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
      <div className="grid grid-cols-2 md:grid-cols-3 2xl:grid-cols-6 gap-2 md:gap-4">
        <MetricCard
          title="Total Dives"
          value={stats?.total_dives || 0}
          color="accent"
          icon={Waves}
        />
        <MetricCard
          title="Success Rate"
          value={`${stats?.success_rate?.toFixed(1) || 0}%`}
          subtitle="Medium or better"
          color="success"
          trend={
            stats?.success_rate && stats.success_rate > 75 ? "up" : "neutral"
          }
          icon={Target}
        />
        <MetricCard
          title="Avg Performance"
          value={stats?.avg_performance?.toFixed(2) || "0.00"}
          subtitle="Calibrated /10"
          color="accent"
          icon={BarChart3}
        />
        {stats?.avg_dd !== undefined && stats.avg_dd > 0 && (
          <MetricCard
            title="Avg DD"
            value={stats.avg_dd.toFixed(1)}
            color="accent"
            icon={Zap}
          />
        )}
        {stats?.max_dd !== undefined && stats.max_dd > 0 && (
          <MetricCard
            title="Max DD"
            value={stats.max_dd.toFixed(1)}
            color="accent"
            icon={Flame}
          />
        )}
        <MetricCard
          title="Training Sessions"
          value={stats?.total_sessions || 0}
          color="accent"
          icon={CalendarDays}
        />
      </div>

      {/* DD Progression */}
      <div className="w-full">
        <DDProgressionChart />
      </div>

      {personalValueChartData.length > 0 && (
        <section
          className="border border-app bg-app-panel p-4 sm:p-5"
          aria-labelledby="dashboard-personal-value"
        >
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2
                id="dashboard-personal-value"
                className="text-xl font-semibold text-app-text"
              >
                Personal Dive Value
              </h2>
            </div>
            <div className="text-right text-sm">
              <div className="text-2xl font-semibold tabular-nums text-app-text">
                {Math.max(
                  ...personalValueChartData.map(
                    (item) => item.personalValue || 0,
                  ),
                ).toFixed(0)}
                <span className="ml-1 text-xs font-normal text-app-muted">
                  highest recent
                </span>
              </div>
              <div className="mt-1 text-xs text-app-muted">
                {personalValueChartData.length} latest eligible attempts
              </div>
            </div>
          </div>
          <div
            className="mt-5 h-56"
            role="img"
            aria-label="Recent Personal Dive Value history"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={personalValueChartData}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="rgba(126,146,156,.18)"
                />
                <XAxis
                  dataKey="dateLabel"
                  stroke="#98a2aa"
                  fontSize={11}
                  minTickGap={36}
                />
                <YAxis domain={[0, 100]} stroke="#98a2aa" fontSize={11} />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#15191c",
                    border: "1px solid rgba(82,96,105,.45)",
                  }}
                  labelStyle={{ color: "#edf2f4" }}
                  formatter={(
                    value: number,
                    _name: string,
                    item: { payload?: (typeof personalValueChartData)[number] },
                  ) => [
                    `${value} / 100 · ${item.payload?.primary_signal || "Emerging"} · ${item.payload?.dive_code}`,
                    "Personal Dive Value",
                  ]}
                />
                <Line
                  type="monotone"
                  dataKey="personalValue"
                  stroke="#54beab"
                  strokeWidth={2.5}
                  dot={{ r: 3, fill: "#54beab" }}
                  activeDot={{ r: 5 }}
                  name="Personal Dive Value"
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </section>
      )}

      {/* Charts Row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Monthly Progression */}
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-app-text mb-4">
            Monthly Progression
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={monthlyChartData}>
              <defs>
                <linearGradient id="colorDives" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor={COLORS.primary}
                    stopOpacity={0.3}
                  />
                  <stop
                    offset="95%"
                    stopColor={COLORS.primary}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(82,96,105,.35)" />
              <XAxis dataKey="monthLabel" stroke="#98a2aa" fontSize={12} />
              <YAxis stroke="#98a2aa" fontSize={12} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#15191c",
                  border: "1px solid rgba(82,96,105,.45)",
                  borderRadius: "8px",
                }}
                labelStyle={{ color: "#edf2f4" }}
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
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-app-text mb-4">
            Performance by Height
          </h2>
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={heightChartData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(82,96,105,.35)" />
              <XAxis
                type="number"
                stroke="#98a2aa"
                fontSize={12}
                domain={[0, 10]}
              />
              <YAxis
                dataKey="name"
                type="category"
                stroke="#98a2aa"
                fontSize={12}
                width={40}
              />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#15191c",
                  border: "1px solid rgba(82,96,105,.45)",
                  borderRadius: "8px",
                }}
                labelStyle={{ color: "#edf2f4" }}
                formatter={(value: number, name: string) => [
                  name === "performance" ? value.toFixed(2) : value,
                  name === "performance"
                    ? "Avg Performance"
                    : name === "dives"
                      ? "Total Dives"
                      : name,
                ]}
              />
              <Bar
                dataKey="performance"
                fill={COLORS.primary}
                radius={[0, 4, 4, 0]}
                name="Avg Performance"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Charts Row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Direction Breakdown */}
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-app-text mb-4">
            By Direction
          </h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={directionChartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(82,96,105,.35)" />
              <XAxis
                dataKey="name"
                stroke="#98a2aa"
                fontSize={11}
                angle={-20}
                textAnchor="end"
                height={50}
              />
              <YAxis stroke="#98a2aa" fontSize={12} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#15191c",
                  border: "1px solid rgba(82,96,105,.45)",
                  borderRadius: "8px",
                }}
                labelStyle={{ color: "#edf2f4" }}
              />
              <Bar
                dataKey="dives"
                fill={COLORS.purple}
                radius={[4, 4, 0, 0]}
                name="Dives"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Success Rate Trend */}
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-app-text mb-4">
            Success Rate Trend
          </h2>
          <ResponsiveContainer width="100%" height={240}>
            <AreaChart data={monthlyChartData}>
              <defs>
                <linearGradient id="colorSuccess" x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="5%"
                    stopColor={COLORS.success}
                    stopOpacity={0.3}
                  />
                  <stop
                    offset="95%"
                    stopColor={COLORS.success}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(82,96,105,.35)" />
              <XAxis dataKey="monthLabel" stroke="#98a2aa" fontSize={11} />
              <YAxis stroke="#98a2aa" fontSize={12} domain={[0, 100]} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "#15191c",
                  border: "1px solid rgba(82,96,105,.45)",
                  borderRadius: "8px",
                }}
                formatter={(value: number) => [
                  `${value.toFixed(1)}%`,
                  "Success Rate",
                ]}
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
        <div className="app-panel">
          <h2 className="text-xl font-semibold text-app-text mb-4">
            Training Focus
          </h2>
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
                label={({ name, percent }) =>
                  `${name} ${(percent * 100).toFixed(0)}%`
                }
                labelLine={false}
              >
                {heightChartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={
                      Object.values(COLORS)[
                        index % Object.values(COLORS).length
                      ]
                    }
                  />
                ))}
              </Pie>
              <Tooltip
                contentStyle={{
                  backgroundColor: "#15191c",
                  border: "1px solid rgba(82,96,105,.45)",
                  borderRadius: "8px",
                }}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Recent Sessions */}
      <div className="app-panel">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <h2 className="app-section-title">Recent Training Sessions</h2>
          <a
            href="/sessions"
            className="text-app-accent hover:text-app-text text-sm"
          >
            View all →
          </a>
        </div>
        <div className="grid gap-2 sm:hidden">
          {recentSessions.map((session) => (
            <article
              key={session.id}
              className="border border-app bg-app-panel-elevated p-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="font-medium text-app-text">
                    {format(parseISO(session.date), "MMM d, yyyy")}
                  </h3>
                  <p className="mt-1 text-xs text-app-muted">
                    {session.total_dives} dives · {session.total_personal_dives}{" "}
                    personal
                  </p>
                </div>
                <SuccessRateBadge value={session.success_rate} />
              </div>
              <div className="mt-3 flex items-center justify-between text-sm">
                <span className="text-app-muted">Average performance</span>
                <PerformanceBadge value={session.avg_performance} />
              </div>
            </article>
          ))}
        </div>
        <div className="app-table-scroll hidden sm:block">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-app text-sm text-app-muted">
                <th className="pb-3 font-medium">Date</th>
                <th className="pb-3 font-medium">Dives</th>
                <th className="pb-3 font-medium">Personal</th>
                <th className="pb-3 font-medium">Avg Performance</th>
                <th className="pb-3 font-medium">Success Rate</th>
              </tr>
            </thead>
            <tbody>
              {recentSessions.map((session) => (
                <tr
                  key={session.id}
                  className="border-b border-app/60 hover:bg-app-panel-elevated"
                >
                  <td className="py-3 text-app-text font-medium">
                    {format(parseISO(session.date), "MMM d, yyyy")}
                  </td>
                  <td className="py-3 text-app-text">{session.total_dives}</td>
                  <td className="py-3 text-app-text">
                    {session.total_personal_dives}
                  </td>
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
  );
}

// Helper Components
function MetricCard({
  title,
  value,
  subtitle,
  color,
  trend,
  icon,
}: {
  title: string;
  value: string | number;
  subtitle?: string;
  color: "accent" | "success";
  trend?: "up" | "down" | "neutral";
  icon: LucideIcon;
}) {
  const colorClasses = {
    accent: "border-app bg-app-panel",
    success: "border-app bg-app-panel",
  };
  const valueColors = {
    accent: "text-app-accent",
    success: "text-green-400",
  };

  return (
    <div
      className={`min-w-0 h-full min-h-[7.75rem] border p-3 transition-colors sm:p-5 ${colorClasses[color]} hover:bg-app-panel-elevated`}
    >
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <p className="min-h-5 break-words text-sm font-medium leading-5 text-app-muted">
            {title}
          </p>
          <p
            className={`app-kpi-value mt-1 text-2xl leading-8 sm:text-3xl sm:leading-9 ${valueColors[color]}`}
          >
            {value}
          </p>
          {subtitle && (
            <p className="break-words text-xs leading-4 text-app-muted mt-1">
              {subtitle}
            </p>
          )}
        </div>
        {React.createElement(icon, {
          className: `h-5 w-5 shrink-0 ${valueColors[color]}`,
          "aria-hidden": true,
        })}
      </div>
    </div>
  );
}

function PerformanceBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-app-muted">-</span>;

  const color =
    value >= 7
      ? "text-green-400"
      : value >= 4.5
        ? "text-amber-400"
        : "text-red-400";
  return <span className={`font-medium ${color}`}>{value.toFixed(2)}</span>;
}

function SuccessRateBadge({ value }: { value: number | null }) {
  if (value === null) return <span className="text-app-muted">-</span>;

  const color =
    value >= 80
      ? "bg-green-500/20 text-green-400"
      : value >= 60
        ? "bg-amber-500/20 text-amber-400"
        : "bg-red-500/20 text-red-400";
  return (
    <span className={`px-2 py-1 rounded text-sm font-medium ${color}`}>
      {value.toFixed(1)}%
    </span>
  );
}

export default Dashboard;
