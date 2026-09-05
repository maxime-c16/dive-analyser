import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import JourneyTimeline from "../components/JourneyTimeline";
import AvoidedDives from "../components/AvoidedDives";
import JourneyNarrative from "../components/JourneyNarrative";
import JourneyWithSync from "../components/JourneyWithSync";
import MentalBlockIndicator from "../components/MentalBlockIndicator";
import { useSyncStatus } from "../hooks/useSyncStatus";
import DDWorkspace from "../components/DDWorkspace";
import {
  AlertTriangle,
  ArrowRight,
  Brain,
  TrendingDown,
  TrendingUp,
} from "lucide-react";

interface JourneyData {
  overview: {
    total_dives: number;
    unique_dive_combinations: number;
    days_of_training: number;
    first_dive_date: string;
    latest_dive_date: string;
  };
  growth: {
    first_month_average: number;
    last_month_average: number;
    improvement: number;
    trajectory: string;
  };
  journey: {
    narrative: string;
  };
  dd_progression?: {
    months: Array<{
      month: string;
      max_dd: number;
      attempts: number;
      breakthroughs: string[];
    }>;
    current_max: number;
    highest_achieved: number;
  };
  psychological?: {
    mental_blocks_detected: number;
    fear_coefficient: number;
    confidence_trend: string;
    emotional_state_data: Array<{
      dive_id: number;
      pre_emotion: string;
      post_emotion: string;
      confidence: number;
    }>;
  };
}

interface Milestone {
  type: string;
  dive_code: string;
  height: string;
  title: string;
  narrative: string;
  date: string;
  significance: number;
}

function Journey() {
  const { currentSync } = useSyncStatus();
  const [journeyData, setJourneyData] = useState<JourneyData | null>(null);
  const [milestones, setMilestones] = useState<Milestone[]>([]);
  const [phaseData, setPhaseData] = useState<any>(null);
  const [psychData, setPsychData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<
    | "timeline"
    | "narrative"
    | "avoided"
    | "phases"
    | "psychology"
    | "dd-progression"
  >("timeline");
  const [minSignificance, setMinSignificance] = useState(1);

  useEffect(() => {
    fetchJourneyData();
  }, []);

  const fetchJourneyData = async () => {
    try {
      setLoading(true);
      const [journeyRes, milestonesRes, phaseRes, fearRes] = await Promise.all([
        api.get("/api/v1/journey"),
        api.get("/api/v1/journey/milestones", {
          params: { min_significance: minSignificance },
        }),
        api.get("/api/v1/journey/phase-analysis"),
        api
          .get("/api/v1/psychology/fear-analysis")
          .catch(() => ({ data: null })),
      ]);
      setJourneyData(journeyRes.data);
      setMilestones(milestonesRes.data.milestones || []);
      setPhaseData(phaseRes.data);
      setPsychData(fearRes.data);
      setError(null);
    } catch (err) {
      console.error("Error fetching journey data:", err);
      setError("Failed to load your journey");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (activeTab === "timeline") {
      fetchJourneyData();
    }
  }, [minSignificance]);

  if (loading) {
    return (
      <div className="app-page">
        <div className="max-w-4xl mx-auto">
          <div className="animate-pulse space-y-4">
            <div className="h-8 bg-gray-700 rounded w-1/3"></div>
            <div className="h-4 bg-gray-700 rounded w-2/3"></div>
            <div className="space-y-4 mt-6">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-24 bg-gray-700 rounded"></div>
              ))}
            </div>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="app-page">
        <div className="max-w-4xl mx-auto">
          <div className="border border-red-500/50 bg-red-500/20 p-4 text-red-400">
            {error}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="border-b border-app bg-app-panel px-4 py-5 sm:px-6 sm:py-6">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-3xl font-semibold sm:text-4xl">
            Your Diving Journey
          </h1>
          <p className="mt-2 max-w-2xl text-app-muted">
            Your story written in water. Every attempt, every breakthrough,
            every moment that shaped you.
          </p>
        </div>
      </div>

      {/* Stats Bar */}
      {journeyData && (
        <div className="border-b border-app bg-app-panel px-4 py-4 sm:px-6">
          <div className="max-w-6xl mx-auto">
            <div className="grid grid-cols-2 gap-x-4 gap-y-5 lg:grid-cols-5">
              <div className="min-w-0">
                <div className="text-gray-400 text-sm mb-1">Total Dives</div>
                <div className="app-kpi-value text-2xl">
                  {journeyData.overview.total_dives}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-gray-400 text-sm mb-1">Unique Dives</div>
                <div className="app-kpi-value text-2xl">
                  {journeyData.overview.unique_dive_combinations}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-gray-400 text-sm mb-1">Training Days</div>
                <div className="app-kpi-value text-2xl">
                  {journeyData.overview.days_of_training}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-gray-400 text-sm mb-1">Improvement</div>
                <div
                  className={`app-kpi-value text-2xl ${journeyData.growth.improvement > 0 ? "text-green-400" : "text-gray-400"}`}
                >
                  {journeyData.growth.improvement > 0 ? "+" : ""}
                  {journeyData.growth.improvement.toFixed(2)}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-gray-400 text-sm mb-1">Trajectory</div>
                <div
                  className={`text-lg font-semibold ${
                    journeyData.growth.trajectory === "improving"
                      ? "text-green-400"
                      : journeyData.growth.trajectory === "plateauing"
                        ? "text-amber-400"
                        : "text-red-400"
                  }`}
                >
                  {journeyData.growth.trajectory}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <nav
        className="border-b border-app bg-app-panel"
        aria-label="Journey sections"
      >
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <label className="block py-3 md:hidden">
            <span className="sr-only">Journey section</span>
            <select
              value={activeTab}
              onChange={(event) =>
                setActiveTab(event.target.value as typeof activeTab)
              }
              className="app-input w-full"
            >
              <option value="narrative">Your story</option>
              <option value="dd-progression">DD progression</option>
              <option value="timeline">Milestones</option>
              <option value="phases">Phase analysis</option>
              <option value="psychology">Psychology</option>
              <option value="avoided">Patterns</option>
            </select>
          </label>
          <div className="app-table-scroll hidden items-center gap-1 md:flex">
            <button
              onClick={() => setActiveTab("narrative")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "narrative"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-gray-400 hover:text-gray-300"
              }`}
            >
              Your Story
            </button>
            <button
              onClick={() => setActiveTab("dd-progression")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "dd-progression"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-gray-400 hover:text-gray-300"
              }`}
            >
              DD Progression
            </button>
            <button
              onClick={() => setActiveTab("timeline")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "timeline"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-gray-400 hover:text-gray-300"
              }`}
            >
              Milestones
            </button>
            <button
              onClick={() => setActiveTab("phases")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "phases"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-gray-400 hover:text-gray-300"
              }`}
            >
              Phase Analysis
            </button>
            <button
              onClick={() => setActiveTab("psychology")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "psychology"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-gray-400 hover:text-gray-300"
              }`}
            >
              Psychology
            </button>
            <button
              onClick={() => setActiveTab("avoided")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "avoided"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-gray-400 hover:text-gray-300"
              }`}
            >
              Patterns
            </button>
          </div>
        </div>
      </nav>

      {/* Content Area */}
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-6">
        <JourneyWithSync onSyncComplete={() => fetchJourneyData()}>
          {activeTab === "narrative" && journeyData && (
            <JourneyNarrative data={journeyData} />
          )}

          {activeTab === "timeline" && (
            <>
              <div className="mb-6 flex flex-col gap-3 border-b border-app pb-4 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="text-2xl font-semibold">Milestones</h2>
                  <p className="mt-1 text-sm text-gray-400">
                    Recorded breakthroughs and progress points. Open any item
                    for the full context.
                  </p>
                </div>
                <div className="flex items-center gap-3">
                  <label className="text-sm text-gray-400">Show:</label>
                  <select
                    value={minSignificance}
                    onChange={(e) =>
                      setMinSignificance(parseInt(e.target.value))
                    }
                    className="app-input text-sm"
                  >
                    <option value={1}>All (1+)</option>
                    <option value={2}>2+</option>
                    <option value={3}>3+</option>
                    <option value={4}>4+</option>
                    <option value={5}>5 only</option>
                  </select>
                </div>
              </div>
              <JourneyTimeline milestones={milestones} />
            </>
          )}

          {activeTab === "phases" && phaseData && (
            <div className="space-y-6">
              <div className="app-panel p-4 sm:p-6">
                <h2 className="text-2xl font-semibold mb-2">
                  Two-Phase Dive Analysis
                </h2>
                <p className="app-section-copy mb-4">
                  Separates takeoff quality from landing quality to identify
                  specific strengths and areas for improvement.
                </p>

                {/* Summary Stats */}
                <div className="grid grid-cols-2 gap-3 mb-6 pb-6 border-b border-app sm:grid-cols-4 sm:gap-4">
                  <div className="min-w-0">
                    <div className="text-gray-400 text-sm mb-1">
                      Total Dives
                    </div>
                    <div className="app-kpi-value text-2xl">
                      {phaseData.summary?.total_dives || 0}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-gray-400 text-sm mb-1">
                      Two-Phase Format
                    </div>
                    <div className="app-kpi-value text-2xl text-app-accent">
                      {phaseData.summary?.two_phase_dives || 0}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-gray-400 text-sm mb-1">
                      Legacy Format
                    </div>
                    <div className="app-kpi-value text-2xl text-blue-400">
                      {phaseData.summary?.legacy_dives || 0}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-gray-400 text-sm mb-1">
                      New Format %
                    </div>
                    <div className="app-kpi-value text-2xl text-green-400">
                      {phaseData.summary?.percentage_new_format || 0}%
                    </div>
                  </div>
                </div>

                {/* Phase 1 Analysis */}
                <div className="mb-8">
                  <div className="mb-4">
                    <h3 className="text-xl font-bold text-cyan-400 mb-2">
                      Phase 1: Hurdle + Flight (Takeoff)
                    </h3>
                    <p className="text-gray-400 text-sm mb-3">
                      {phaseData.phase1_analysis?.description}
                    </p>
                    <div className="app-kpi-value mb-2 text-2xl">
                      Average Score: {phaseData.phase1_analysis?.average} / 10
                    </div>
                  </div>

                  {/* Phase 1 Distribution */}
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                    {phaseData.phase1_analysis?.distribution &&
                      Object.entries(
                        phaseData.phase1_analysis.distribution,
                      ).map(([score, count]) => (
                        <div
                          key={score}
                          className="border border-app bg-app-panel-elevated p-3 text-center"
                        >
                          <div className="text-lg font-bold text-cyan-400">
                            {score}
                          </div>
                          <div className="text-gray-400 text-xs">
                            {Number(count)} dives
                          </div>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Phase 2 Analysis */}
                <div className="mb-8">
                  <div className="mb-4">
                    <h3 className="text-xl font-bold text-cyan-400 mb-2">
                      Phase 2: Opening + Entry (Landing)
                    </h3>
                    <p className="text-gray-400 text-sm mb-3">
                      {phaseData.phase2_analysis?.description}
                    </p>
                    <div className="app-kpi-value mb-2 text-2xl">
                      Average Score: {phaseData.phase2_analysis?.average} / 10
                    </div>
                  </div>

                  {/* Phase 2 Distribution */}
                  <div className="grid grid-cols-2 gap-2 sm:grid-cols-5">
                    {phaseData.phase2_analysis?.distribution &&
                      Object.entries(
                        phaseData.phase2_analysis.distribution,
                      ).map(([score, count]) => (
                        <div
                          key={score}
                          className="border border-app bg-app-panel-elevated p-3 text-center"
                        >
                          <div className="text-lg font-bold text-cyan-400">
                            {score}
                          </div>
                          <div className="text-gray-400 text-xs">
                            {Number(count)} dives
                          </div>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Phase Combinations */}
                {phaseData.phase_combinations?.distribution && (
                  <div className="mb-8">
                    <h3 className="text-xl font-bold text-cyan-400 mb-4">
                      Most Common Phase Combinations
                    </h3>
                    <div className="space-y-2">
                      {Object.entries(phaseData.phase_combinations.distribution)
                        .sort(([, a], [, b]) => (b as number) - (a as number))
                        .slice(0, 5)
                        .map(([combo, count]) => (
                          <div
                            key={combo}
                            className="flex items-center justify-between border border-app bg-app-panel-elevated p-3"
                          >
                            <div className="font-mono text-cyan-400">
                              {combo}
                            </div>
                            <div className="text-gray-400">
                              {Number(count)} dives
                            </div>
                          </div>
                        ))}
                    </div>
                  </div>
                )}

                {/* Coaching Insights */}
                {phaseData.coaching_insights &&
                  phaseData.coaching_insights.length > 0 && (
                    <div>
                      <h3 className="text-xl font-bold text-green-400 mb-4">
                        Coaching Insights
                      </h3>
                      <div className="space-y-3">
                        {phaseData.coaching_insights.map(
                          (insight: any, idx: number) => (
                            <div
                              key={idx}
                              className="border border-green-500/30 bg-green-500/10 p-4"
                            >
                              <div className="font-bold text-green-400 mb-1">
                                {insight.pattern}
                              </div>
                              <p className="text-gray-300 text-sm">
                                {insight.coaching}
                              </p>
                            </div>
                          ),
                        )}
                      </div>
                    </div>
                  )}

                {/* Recommendation */}
                {phaseData.recommendation && (
                  <div className="mt-6 border border-blue-500/30 bg-blue-500/10 p-4">
                    <p className="text-blue-300">{phaseData.recommendation}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "dd-progression" && <DDWorkspace />}

          {activeTab === "psychology" && (
            <div className="space-y-6">
              {/* Mental Block Detection */}
              <div className="app-panel p-4 sm:p-6">
                <h3 className="text-xl font-bold text-yellow-400 mb-4">
                  Mental Block Status
                </h3>
                <MentalBlockIndicator />
              </div>

              <div className="app-panel p-4 sm:p-6">
                <h2 className="mb-2 flex items-center gap-2 text-2xl font-bold">
                  <Brain
                    className="h-6 w-6 text-purple-400"
                    aria-hidden="true"
                  />
                  Your Psychological Profile
                </h2>
                <p className="app-section-copy mb-6">
                  Understanding your emotions, confidence, and mental blocks
                  helps you grow as a diver.
                </p>

                {journeyData?.psychological ? (
                  <>
                    {/* Mental Health Indicators */}
                    <div className="grid grid-cols-1 gap-3 mb-8 pb-8 border-b border-app sm:grid-cols-3">
                      <div className="border border-purple-500/30 bg-purple-500/10 p-4">
                        <div className="text-gray-400 text-sm mb-2">
                          Mental Blocks Detected
                        </div>
                        <div className="app-kpi-value text-2xl text-purple-400">
                          {journeyData.psychological.mental_blocks_detected ||
                            0}
                        </div>
                      </div>
                      <div className="border border-blue-500/30 bg-blue-500/10 p-4">
                        <div className="text-gray-400 text-sm mb-2">
                          Fear vs Difficulty
                        </div>
                        <div className="app-kpi-value text-2xl text-blue-400">
                          {journeyData.psychological.fear_coefficient
                            ? journeyData.psychological.fear_coefficient.toFixed(
                                2,
                              )
                            : "1.0"}
                        </div>
                        <div className="text-xs text-gray-500 mt-1">
                          Coefficient ratio
                        </div>
                      </div>
                      <div className="border border-green-500/30 bg-green-500/10 p-4">
                        <div className="text-gray-400 text-sm mb-2">
                          Confidence Trend
                        </div>
                        <div
                          className={`app-kpi-value text-2xl ${
                            journeyData.psychological.confidence_trend ===
                            "improving"
                              ? "text-green-400"
                              : journeyData.psychological.confidence_trend ===
                                  "stable"
                                ? "text-yellow-400"
                                : "text-red-400"
                          }`}
                        >
                          {journeyData.psychological.confidence_trend
                            ? journeyData.psychological.confidence_trend
                                .charAt(0)
                                .toUpperCase() +
                              journeyData.psychological.confidence_trend.slice(
                                1,
                              )
                            : "Stable"}
                        </div>
                      </div>
                    </div>

                    {/* Mental Blocks Alert */}
                    {journeyData.psychological.mental_blocks_detected > 0 && (
                      <div className="mb-6 border border-yellow-500/30 bg-yellow-500/10 p-4">
                        <div className="mb-2 flex items-center gap-2 font-bold text-yellow-400">
                          <AlertTriangle
                            className="h-4 w-4"
                            aria-hidden="true"
                          />
                          Mental Block Detected
                        </div>
                        <p className="text-gray-300 text-sm">
                          You've been attempting the same maximum difficulty for
                          3+ months. This is a natural plateau! Consider:
                        </p>
                        <ul className="text-gray-300 text-sm list-disc list-inside mt-2 space-y-1">
                          <li>Taking a break and returning refreshed</li>
                          <li>Focusing on form on easier dives</li>
                          <li>Using visualization and mental rehearsal</li>
                          <li>Building confidence with supervised attempts</li>
                        </ul>
                      </div>
                    )}

                    {/* Confidence Over Time */}
                    <div className="border border-app bg-app-panel-elevated p-4">
                      <h3 className="text-lg font-bold text-green-400 mb-3">
                        Your Growth Arc
                      </h3>
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-gray-400">
                            First Month Avg Performance
                          </span>
                          <span className="text-white font-bold">
                            {journeyData.growth.first_month_average.toFixed(2)}{" "}
                            / 10
                          </span>
                        </div>
                        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-cyan-500 to-blue-500"
                            style={{
                              width: `${(journeyData.growth.first_month_average / 10) * 100}%`,
                            }}
                          />
                        </div>

                        <div className="flex items-center justify-between mt-4">
                          <span className="text-gray-400">
                            Latest Month Avg Performance
                          </span>
                          <span className="text-white font-bold">
                            {journeyData.growth.last_month_average.toFixed(2)} /
                            10
                          </span>
                        </div>
                        <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                          <div
                            className="h-full bg-gradient-to-r from-green-500 to-emerald-500"
                            style={{
                              width: `${(journeyData.growth.last_month_average / 10) * 100}%`,
                            }}
                          />
                        </div>

                        <div className="mt-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded">
                          <div className="text-blue-400 font-bold">
                            Overall Improvement
                          </div>
                          <div className="text-white text-lg">
                            {journeyData.growth.improvement > 0 ? "+" : ""}
                            {journeyData.growth.improvement.toFixed(2)} points
                          </div>
                          <div className="text-gray-400 text-sm mt-1">
                            {journeyData.growth.trajectory === "improving" ? (
                              <span className="inline-flex items-center gap-1">
                                <TrendingUp className="h-4 w-4" />
                                You&apos;re getting better
                              </span>
                            ) : journeyData.growth.trajectory ===
                              "plateauing" ? (
                              <span className="inline-flex items-center gap-1">
                                <ArrowRight className="h-4 w-4" />
                                Holding steady
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1">
                                <TrendingDown className="h-4 w-4" />
                                Room for growth
                              </span>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>

                    {/* Emotional State Placeholder */}
                    <div className="mt-4 border border-app bg-app-panel-elevated p-4">
                      <h3 className="text-lg font-bold text-purple-400 mb-3">
                        Emotional Tracking
                      </h3>
                      <p className="text-gray-400 text-sm mb-3">
                        Ready to start logging your emotional state? This helps
                        us understand your confidence patterns and identify
                        mental blocks.
                      </p>
                      <div className="inline-block border border-purple-400/40 bg-purple-500/15 px-4 py-2 text-sm font-medium text-purple-200 transition-colors hover:bg-purple-500/25">
                        Start Tracking Emotions
                      </div>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-8 text-gray-400">
                    <div className="animate-pulse">
                      Loading your psychological profile...
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}

          {activeTab === "avoided" && <AvoidedDives />}
        </JourneyWithSync>
      </div>
    </div>
  );
}

export default Journey;
