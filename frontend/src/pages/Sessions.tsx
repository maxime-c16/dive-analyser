import React, { useEffect, useState } from "react";
import { getNavigationData } from "../services/navigationData";
import { format, parseISO, isToday, isYesterday, isThisWeek } from "date-fns";
import {
  CalendarDays,
  TrendingUp,
  TrendingDown,
  Minus,
  Waves,
  Users,
  UserRound,
} from "lucide-react";
import SessionDetail from "../components/SessionDetail";
import RecentProgress from "../components/RecentProgress";
import SessionDirectionIndicator from "../components/SessionDirectionIndicator";
import { useTranslation } from "react-i18next";
import { appLocale } from "../utils/dateLocale";
import { useAuth } from "../contexts/AuthContext";
import {
  performanceBorder,
  performanceColor,
} from "../utils/performanceScoring";

interface Session {
  id: number;
  date: string;
  location?: string;
  total_dives: number;
  total_personal_dives: number;
  avg_performance?: number;
  success_rate?: number;
  notes?: string;
}

function Sessions() {
  const { t } = useTranslation();
  const { user } = useAuth();
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(50);
  // Friends see everyone's dives by default (no diver bindings held).
  const [diverScope, setDiverScope] = useState<"self" | "all">(
    (!user || user.divers?.length) ? "self" : "all",
  );
  const [selectedSession, setSelectedSession] = useState<Session | null>(null);

  useEffect(() => {
    fetchSessions();
  }, [limit, diverScope]);

  const fetchSessions = async () => {
    try {
      setLoading(true);
      const response = await getNavigationData("/api/v1/sessions", { limit, diver_scope: diverScope });
      setSessions(response.data);
      setError(null);
    } catch (err) {
      console.error("Error fetching sessions:", err);
      setError("sessions.errorLoad");
    } finally {
      setLoading(false);
    }
  };

  // Group sessions by month
  const groupedSessions = sessions.reduce(
    (groups, session) => {
      const monthKey = format(parseISO(session.date), "MMMM yyyy", { locale: appLocale() });
      if (!groups[monthKey]) {
        groups[monthKey] = [];
      }
      groups[monthKey].push(session);
      return groups;
    },
    {} as { [key: string]: Session[] },
  );

  // Calculate stats
  const stats = {
    totalSessions: sessions.length,
    totalDives: sessions.reduce((sum, s) => sum + s.total_dives, 0),
    avgDivesPerSession:
      sessions.length > 0
        ? sessions.reduce((sum, s) => sum + s.total_dives, 0) / sessions.length
        : 0,
  };

  const getDateLabel = (dateStr: string) => {
    const date = parseISO(dateStr);
    if (isToday(date)) return t("sessions.today");
    if (isYesterday(date)) return t("sessions.yesterday");
    return format(date, "EEEE, MMMM d", { locale: appLocale() });
  };

  const getPerformanceColor = (perf: number | undefined) => {
    if (!perf) return "text-app-muted";
    return performanceColor(perf);
  };

  const getSuccessRateColor = (rate: number | undefined) => {
    if (!rate) return "bg-app-panel-elevated text-app-muted";
    if (rate >= 80) return "bg-green-500/20 text-green-400";
    if (rate >= 60) return "bg-amber-500/20 text-amber-400";
    return "bg-red-500/20 text-red-400";
  };

  const getSessionBorderColor = (perf: number | undefined) => {
    if (!perf) return "border-app";
    return performanceBorder(perf);
  };

  const calculateTrend = (index: number) => {
    const currentSession = Object.values(groupedSessions).flat()[index];
    const previousSession = Object.values(groupedSessions).flat()[index + 1];

    if (!currentSession || !previousSession) return null;

    const perfDiff =
      (currentSession.avg_performance || 0) -
      (previousSession.avg_performance || 0);

    return {
      isPositive: perfDiff > 0,
      isNeutral: perfDiff === 0,
    };
  };

  const TrendIndicator = ({ trend }: { trend: any }) => {
    if (!trend) return null;
    if (trend.isNeutral) return <Minus className="w-4 h-4 text-app-muted" />;
    return trend.isPositive ? (
      <TrendingUp className="w-4 h-4 text-green-400" />
    ) : (
      <TrendingDown className="w-4 h-4 text-red-400" />
    );
  };

  const getPreviousSession = (sessionId: number): Session | undefined => {
    const allSessions = Object.values(groupedSessions).flat();
    const currentIndex = allSessions.findIndex((s) => s.id === sessionId);
    return allSessions[currentIndex + 1];
  };

  return (
    <div className="app-page">
      {/* Session Detail Modal */}
      {selectedSession && (
        <SessionDetail
          session={selectedSession}
          previousSession={getPreviousSession(selectedSession.id)}
          allSessions={sessions}
          diverScope={diverScope}
          onClose={() => setSelectedSession(null)}
        />
      )}

      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <h1 className="text-3xl font-bold text-app-text">{t("sessions.title")}</h1>

        {/* Quick Stats */}
        <div className="grid w-full grid-cols-2 gap-2 sm:flex sm:w-auto sm:gap-4">
          <div className="app-panel min-w-0 px-3 py-2 sm:px-4">
            <span className="text-app-muted text-sm">{t("sessions.sessions")}</span>
            <span className="app-kpi-value ml-2">{stats.totalSessions}</span>
          </div>
          <div className="app-panel min-w-0 px-3 py-2 sm:px-4">
            <span className="text-app-muted text-sm">{t("dashboard.totalDives")}</span>
            <span className="app-kpi-value ml-2 text-app-accent">
              {stats.totalDives}
            </span>
          </div>
          <div className="app-panel col-span-2 min-w-0 px-3 py-2 sm:col-span-1 sm:px-4">
            <span className="text-app-muted text-sm">{t("sessions.avgPerSession")}</span>
            <span className="app-kpi-value ml-2 text-app-text">
              {stats.avgDivesPerSession.toFixed(1)}
            </span>
          </div>
        </div>
      </div>

      <div
        className="inline-flex w-full border border-app bg-app-panel p-1 sm:w-auto"
        role="group"
        aria-label={t("sessions.scopeAria")}
      >
        <button
          type="button"
          onClick={() => setDiverScope("self")}
          className={`touch-target flex-1 gap-2 px-3 text-sm sm:flex-none ${diverScope === "self" ? "bg-app-panel-elevated text-app-accent" : "text-app-muted"}`}
        >
          <UserRound className="h-4 w-4" />
          {t("dives.myDives")}
        </button>
        <button
          type="button"
          onClick={() => setDiverScope("all")}
          className={`touch-target flex-1 gap-2 px-3 text-sm sm:flex-none ${diverScope === "all" ? "bg-app-panel-elevated text-app-accent" : "text-app-muted"}`}
        >
          <Users className="h-4 w-4" />
          {t("sessions.everyone")}
        </button>
      </div>

      {/* Recent Progress */}
      {!loading && !error && sessions.length > 0 && (
        <RecentProgress
          sessions={sessions}
          onSessionClick={setSelectedSession}
        />
      )}

      {/* Loading */}
      {loading && (
        <div className="flex items-center justify-center py-12">
          <div className="w-12 h-12 border-4 border-app-accent border-t-transparent rounded-full animate-spin"></div>
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="border border-red-500/30 bg-red-500/10 p-4 text-red-400">
          {t(error ?? "sessions.errorLoad")}
        </div>
      )}

      {/* Sessions by Month */}
      {!loading && !error && (
        <div className="space-y-8">
          {Object.entries(groupedSessions).map(([month, monthSessions]) => (
            <div key={month}>
              <h2 className="text-lg font-semibold text-app-muted mb-4 flex items-center gap-2">
                <span className="w-2 h-2 bg-app-accent rounded-full"></span>
                {month}
                <span className="text-sm font-normal text-app-muted">
                  ({monthSessions.length} {t("sessions.sessions")})
                </span>
              </h2>

              <div className="grid gap-4">
                {monthSessions.map((session, sessionIndex) => {
                  const trend = calculateTrend(
                    Object.values(groupedSessions).flat().indexOf(session),
                  );
                  return (
                    <button
                      key={session.id}
                      onClick={() => setSelectedSession(session)}
                      className={`touch-target app-panel w-full p-4 text-left transition-colors hover:border-app-accent sm:p-5 ${getSessionBorderColor(session.avg_performance)}`}
                    >
                      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4">
                        {/* Date and Location */}
                        <div className="flex-1">
                          <div className="flex items-center gap-3">
                            <div className="flex h-12 w-12 items-center justify-center bg-app-accent-soft">
                              <Waves
                                className="h-6 w-6 text-app-accent"
                                aria-hidden="true"
                              />
                            </div>
                            <div>
                              <h3 className="text-lg font-semibold text-app-text">
                                {getDateLabel(session.date)}
                              </h3>
                              <p className="text-app-muted text-sm">
                                {session.location ||
                                  format(parseISO(session.date), "EEEE", { locale: appLocale() })}
                              </p>
                            </div>
                          </div>
                        </div>

                        {/* Stats */}
                        <div className="grid grid-cols-2 gap-x-7 gap-y-4 sm:flex sm:flex-wrap sm:gap-6 lg:gap-8">
                          <div className="text-center">
                            <p className="app-kpi-value text-2xl">
                              {session.total_dives}
                            </p>
                            <p className="text-xs text-app-muted">
                              {diverScope === "self"
                                ? t("sessions.myAttempts")
                                : t("sessions.inScope")}
                            </p>
                          </div>
                          <div className="text-center">
                            <p className="app-kpi-value text-2xl text-app-accent">
                              {session.total_personal_dives}
                            </p>
                            <p className="text-xs text-app-muted">{t("analysis.scored")}</p>
                          </div>
                          <div className="text-center">
                            <div className="flex items-center justify-center gap-2">
                              <p
                                className={`app-kpi-value text-2xl ${getPerformanceColor(session.avg_performance)}`}
                              >
                                {session.avg_performance?.toFixed(2) || "-"}
                              </p>
                              {trend && <TrendIndicator trend={trend} />}
                            </div>
                            <p className="text-xs text-app-muted">{t("dashboard.avgPerformance")}</p>
                          </div>
                          <div className="text-center">
                            <span
                              className={`inline-block px-3 py-1 text-sm font-bold tabular-nums ${getSuccessRateColor(session.success_rate)}`}
                            >
                              {session.success_rate
                                ? `${session.success_rate.toFixed(0)}%`
                                : "-"}
                            </span>
                            <p className="text-xs text-app-muted mt-1">
                              {t("analysis.success")}
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* Notes (if any) */}
                      {session.notes && (
                        <div className="mt-4 border-t border-app pt-4">
                          <p className="text-app-muted text-sm">
                            {session.notes}
                          </p>
                        </div>
                      )}

                      {/* Performance bar */}
                      <div className="mt-4">
                        <div className="h-1 overflow-hidden bg-app-border">
                          <div
                            className={`h-full transition-all ${
                              (session.success_rate || 0) >= 80
                                ? "bg-green-500"
                                : (session.success_rate || 0) >= 60
                                  ? "bg-amber-500"
                                  : "bg-red-500"
                            }`}
                            style={{ width: `${session.success_rate || 0}%` }}
                          />
                        </div>
                      </div>

                      {/* Direction Indicators */}
                      <div className="mt-4 border-t border-app pt-4">
                        <SessionDirectionIndicator
                          sessionId={session.id}
                          diverScope={diverScope}
                        />
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Empty state */}
      {!loading && !error && sessions.length === 0 && (
        <div className="text-center py-16">
          <CalendarDays
            className="mx-auto mb-4 h-12 w-12 text-app-muted"
            aria-hidden="true"
          />
          <p className="text-app-muted text-xl">{t("sessions.none")}</p>
        </div>
      )}

      {/* Load more */}
      {!loading && sessions.length >= limit && (
        <div className="text-center">
          <button
            onClick={() => setLimit(limit + 50)}
            className="border border-app bg-app-panel px-6 py-2 text-app-text transition-colors hover:border-app-accent hover:bg-app-panel-elevated"
          >
            {t("sessions.loadMore")}
          </button>
        </div>
      )}
    </div>
  );
}

export default Sessions;
