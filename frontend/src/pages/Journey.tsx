import React, { useEffect, useState } from "react";
import { api } from "../services/api";
import JourneyTimeline from "../components/JourneyTimeline";
import AvoidedDives from "../components/AvoidedDives";
import JourneyNarrative from "../components/JourneyNarrative";
import JourneyWithSync from "../components/JourneyWithSync";
import MentalBlockIndicator from "../components/MentalBlockIndicator";
import { useSyncStatus } from "../hooks/useSyncStatus";
import DDWorkspace from "../components/DDWorkspace";
import { AlertTriangle, Brain } from "lucide-react";
import { useTranslation } from "react-i18next";

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
  const { t } = useTranslation();
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
      setError("journey.errorLoad");
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
            <div className="h-8 bg-app-panel-elevated rounded w-1/3"></div>
            <div className="h-4 bg-app-panel-elevated rounded w-2/3"></div>
            <div className="space-y-4 mt-6">
              {[1, 2, 3].map((i) => (
                <div key={i} className="h-24 bg-app-panel-elevated rounded"></div>
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
            {t(error ?? "journey.errorLoad")}
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
            {t("journey.title")}
          </h1>
        </div>
      </div>

      {/* Stats Bar */}
      {journeyData && (
        <div className="border-b border-app bg-app-panel px-4 py-4 sm:px-6">
          <div className="max-w-6xl mx-auto">
            <div className="grid grid-cols-2 gap-x-4 gap-y-5 lg:grid-cols-5">
              <div className="min-w-0">
                <div className="text-app-muted text-sm mb-1">{t("dashboard.totalDives")}</div>
                <div className="app-kpi-value text-2xl">
                  {journeyData.overview.total_dives}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-app-muted text-sm mb-1">{t("journey.uniqueDives")}</div>
                <div className="app-kpi-value text-2xl">
                  {journeyData.overview.unique_dive_combinations}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-app-muted text-sm mb-1">{t("journey.trainingDays")}</div>
                <div className="app-kpi-value text-2xl">
                  {journeyData.overview.days_of_training}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-app-muted text-sm mb-1">{t("journey.improvement")}</div>
                <div
                  className={`app-kpi-value text-2xl ${journeyData.growth.improvement > 0 ? "text-green-400" : "text-app-muted"}`}
                >
                  {journeyData.growth.improvement > 0 ? "+" : ""}
                  {journeyData.growth.improvement.toFixed(2)}
                </div>
              </div>
              <div className="min-w-0">
                <div className="text-app-muted text-sm mb-1">{t("journey.trajectory")}</div>
                <div
                  className={`text-lg font-semibold ${
                    journeyData.growth.trajectory === "improving"
                      ? "text-green-400"
                      : journeyData.growth.trajectory === "plateauing"
                        ? "text-amber-400"
                        : "text-red-400"
                  }`}
                >
                  {t(`analysis.trendDirection.${journeyData.growth.trajectory}`, { defaultValue: journeyData.growth.trajectory })}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <nav
        className="border-b border-app bg-app-panel"
        aria-label={t("journey.sectionsAria")}
      >
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <label className="block py-3 md:hidden">
            <span className="sr-only">{t("journey.section")}</span>
            <select
              value={activeTab}
              onChange={(event) =>
                setActiveTab(event.target.value as typeof activeTab)
              }
              className="app-input w-full"
            >
              <option value="narrative">{t("journey.yourStory")}</option>
              <option value="dd-progression">{t("journey.ddProgression")}</option>
              <option value="timeline">{t("journey.milestones")}</option>
              <option value="phases">{t("journey.phaseAnalysis")}</option>
              <option value="psychology">{t("journey.psychology")}</option>
              <option value="avoided">{t("journey.patterns")}</option>
            </select>
          </label>
          <div className="app-table-scroll hidden items-center gap-1 md:flex">
            <button
              onClick={() => setActiveTab("narrative")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "narrative"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              {t("journey.yourStory")}
            </button>
            <button
              onClick={() => setActiveTab("dd-progression")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "dd-progression"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              {t("journey.ddProgression")}
            </button>
            <button
              onClick={() => setActiveTab("timeline")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "timeline"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              {t("journey.milestones")}
            </button>
            <button
              onClick={() => setActiveTab("phases")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "phases"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              {t("journey.phaseAnalysis")}
            </button>
            <button
              onClick={() => setActiveTab("psychology")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "psychology"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              {t("journey.psychology")}
            </button>
            <button
              onClick={() => setActiveTab("avoided")}
              className={`shrink-0 border-b-2 px-3 py-3 text-sm font-medium transition-colors focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-app-accent ${
                activeTab === "avoided"
                  ? "border-app-accent text-app-accent"
                  : "border-transparent text-app-muted hover:text-app-text"
              }`}
            >
              {t("journey.patterns")}
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
                <h2 className="text-2xl font-semibold">{t("journey.milestones")}</h2>
                <div className="flex items-center gap-3">
                  <label className="text-sm text-app-muted">{t("journey.show")}:</label>
                  <select
                    value={minSignificance}
                    onChange={(e) =>
                      setMinSignificance(parseInt(e.target.value))
                    }
                    className="app-input text-sm"
                  >
                    <option value={1}>{t("journey.all1plus")}</option>
                    <option value={2}>2+</option>
                    <option value={3}>3+</option>
                    <option value={4}>4+</option>
                    <option value={5}>{t("journey.only5")}</option>
                  </select>
                </div>
              </div>
              <JourneyTimeline milestones={milestones} />
            </>
          )}

          {activeTab === "phases" && phaseData && (
            <div className="space-y-6">
              <div className="app-panel p-4 sm:p-6">
                <h2 className="text-2xl font-semibold mb-4">
                  {t("journey.twoPhaseAnalysis")}
                </h2>

                {/* Summary Stats */}
                <div className="grid grid-cols-2 gap-3 mb-6 pb-6 border-b border-app sm:grid-cols-4 sm:gap-4">
                  <div className="min-w-0">
                    <div className="text-app-muted text-sm mb-1">
                      Total Dives
                    </div>
                    <div className="app-kpi-value text-2xl">
                      {phaseData.summary?.total_dives || 0}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-app-muted text-sm mb-1">
                      {t("journey.twoPhaseFormat")}
                    </div>
                    <div className="app-kpi-value text-2xl text-app-accent">
                      {phaseData.summary?.two_phase_dives || 0}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-app-muted text-sm mb-1">
                      {t("journey.legacyFormat")}
                    </div>
                    <div className="app-kpi-value text-2xl text-app-accent">
                      {phaseData.summary?.legacy_dives || 0}
                    </div>
                  </div>
                  <div className="min-w-0">
                    <div className="text-app-muted text-sm mb-1">
                      {t("journey.newFormatPct")}
                    </div>
                    <div className="app-kpi-value text-2xl text-green-400">
                      {phaseData.summary?.percentage_new_format || 0}%
                    </div>
                  </div>
                </div>

                {/* Phase 1 Analysis */}
                <div className="mb-8">
                  <div className="mb-4">
                    <h3 className="text-xl font-bold text-app-accent mb-2">
                      {t("journey.phase1Title")}
                    </h3>
                    <p className="text-app-muted text-sm mb-3">
                      {phaseData.phase1_analysis?.description}
                    </p>
                    <div className="app-kpi-value mb-2 text-2xl">
                      {t("journey.averageScore")}: {phaseData.phase1_analysis?.average} / 10
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
                          <div className="text-lg font-bold text-app-accent">
                            {score}
                          </div>
                          <div className="text-app-muted text-xs">
                            {Number(count)} {t("dashboard.dives")}
                          </div>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Phase 2 Analysis */}
                <div className="mb-8">
                  <div className="mb-4">
                    <h3 className="text-xl font-bold text-app-accent mb-2">
                      {t("journey.phase2Title")}
                    </h3>
                    <p className="text-app-muted text-sm mb-3">
                      {phaseData.phase2_analysis?.description}
                    </p>
                    <div className="app-kpi-value mb-2 text-2xl">
                      {t("journey.averageScore")}: {phaseData.phase2_analysis?.average} / 10
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
                          <div className="text-lg font-bold text-app-accent">
                            {score}
                          </div>
                          <div className="text-app-muted text-xs">
                            {Number(count)} dives
                          </div>
                        </div>
                      ))}
                  </div>
                </div>

                {/* Phase Combinations */}
                {phaseData.phase_combinations?.distribution && (
                  <div className="mb-8">
                    <h3 className="text-xl font-bold text-app-accent mb-4">
                      {t("journey.commonCombinations")}
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
                            <div className="font-mono text-app-accent">
                              {combo}
                            </div>
                            <div className="text-app-muted">
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
                        {t("journey.coachingInsights")}
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
                              <p className="text-app-text text-sm">
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
                  <div className="mt-6 border border-app-accent bg-app-accent-soft p-4">
                    <p className="text-app-accent">{phaseData.recommendation}</p>
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
                  {t("journey.mentalBlockStatus")}
                </h3>
                <MentalBlockIndicator />
              </div>

              <div className="app-panel p-4 sm:p-6">
                <h2 className="mb-6 flex items-center gap-2 text-2xl font-bold">
                  <Brain
                    className="h-6 w-6 text-app-accent"
                    aria-hidden="true"
                  />
                  {t("journey.psychologicalProfile")}
                </h2>

                {journeyData?.psychological ? (
                  <>
                    {/* Mental Health Indicators */}
                    <div className="grid grid-cols-1 gap-3 mb-8 pb-8 border-b border-app sm:grid-cols-3">
                      <div className="border border-app-accent bg-app-accent-soft p-4">
                        <div className="text-app-muted text-sm mb-2">
                          {t("journey.mentalBlocksDetected")}
                        </div>
                        <div className="app-kpi-value text-2xl text-app-accent">
                          {journeyData.psychological.mental_blocks_detected ||
                            0}
                        </div>
                      </div>
                      <div className="border border-app-accent bg-app-accent-soft p-4">
                        <div className="text-app-muted text-sm mb-2">
                          {t("journey.fearVsDifficulty")}
                        </div>
                        <div className="app-kpi-value text-2xl text-app-accent">
                          {journeyData.psychological.fear_coefficient
                            ? journeyData.psychological.fear_coefficient.toFixed(
                                2,
                              )
                            : "1.0"}
                        </div>
                      </div>
                      <div className="border border-green-500/30 bg-green-500/10 p-4">
                        <div className="text-app-muted text-sm mb-2">
                          {t("journey.confidenceTrend")}
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
                            : t("journey.stable")}
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
                          {t("journey.mentalBlockDetected")}
                        </div>
                        <p className="text-app-text text-sm">
                          {t("journey.mentalBlockDetail")}
                        </p>
                      </div>
                    )}

                    {/* Confidence Over Time */}
                    <div className="border border-app bg-app-panel-elevated p-4">
                      <h3 className="text-lg font-bold text-green-400 mb-3">
                        {t("journey.growth")}
                      </h3>
                      <div className="space-y-2">
                        <div className="flex items-center justify-between">
                          <span className="text-app-muted">
                            {t("journey.firstMonthAvg")}
                          </span>
                          <span className="text-app-text font-bold">
                            {journeyData.growth.first_month_average.toFixed(2)}{" "}
                            / 10
                          </span>
                        </div>
                        <div className="h-2 bg-app-border rounded-full overflow-hidden">
                          <div
                            className="h-full bg-app-accent"
                            style={{
                              width: `${(journeyData.growth.first_month_average / 10) * 100}%`,
                            }}
                          />
                        </div>

                        <div className="flex items-center justify-between mt-4">
                          <span className="text-app-muted">
                            {t("journey.latestMonthAvg")}
                          </span>
                          <span className="text-app-text font-bold">
                            {journeyData.growth.last_month_average.toFixed(2)} /
                            10
                          </span>
                        </div>
                        <div className="h-2 bg-app-border rounded-full overflow-hidden">
                          <div
                            className="h-full bg-green-500"
                            style={{
                              width: `${(journeyData.growth.last_month_average / 10) * 100}%`,
                            }}
                          />
                        </div>

                        <div className="mt-4 p-3 bg-app-accent-soft border border-app-accent rounded">
                          <div className="text-app-accent font-bold">
                            {t("journey.overallImprovement")}
                          </div>
                          <div className="text-app-text text-lg">
                            {journeyData.growth.improvement > 0 ? "+" : ""}
                            {journeyData.growth.improvement.toFixed(2)} {t("analysis.points")}
                          </div>
                        </div>
                      </div>
                    </div>

                  </>
                ) : (
                  <div className="text-center py-8 text-app-muted">
                    {t("journey.noPsychology")}
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
