import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import JourneyTimeline from '../components/JourneyTimeline'
import AvoidedDives from '../components/AvoidedDives'
import JourneyNarrative from '../components/JourneyNarrative'
import JourneyWithSync from '../components/JourneyWithSync'
import MentalBlockIndicator from '../components/MentalBlockIndicator'
import MentalBlockAnalysis from '../components/MentalBlockAnalysis'
import RecoveryPlanDisplay from '../components/RecoveryPlanDisplay'
import DegreeOfDifficultyDisplay from '../components/DegreeOfDifficultyDisplay'
import { useSyncStatus } from '../hooks/useSyncStatus'

interface JourneyData {
  journey_id?: number
  overview: {
    total_dives: number
    unique_dive_combinations: number
    days_of_training: number
    first_dive_date: string
    latest_dive_date: string
  }
  growth: {
    first_month_average: number
    last_month_average: number
    improvement: number
    trajectory: string
  }
  journey: {
    narrative: string
  }
  dd_progression?: {
    months: Array<{
      month: string
      max_dd: number
      attempts: number
      breakthroughs: string[]
    }>
    current_max: number
    highest_achieved: number
  }
  psychological?: {
    mental_blocks_detected: number
    fear_coefficient: number
    confidence_trend: string
    emotional_state_data: Array<{
      dive_id: number
      pre_emotion: string
      post_emotion: string
      confidence: number
    }>
  }
}

interface Milestone {
  type: string
  dive_code: string
  height: string
  title: string
  narrative: string
  date: string
  significance: number
}

function Journey() {
  const { currentSync } = useSyncStatus()
  const [journeyData, setJourneyData] = useState<JourneyData | null>(null)
  const [journeyId, setJourneyId] = useState<number | null>(null)
  const [milestones, setMilestones] = useState<Milestone[]>([])
  const [phaseData, setPhaseData] = useState<any>(null)
  const [psychData, setPsychData] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState<'timeline' | 'narrative' | 'avoided' | 'phases' | 'psychology' | 'dd-progression'>('timeline')
  const [minSignificance, setMinSignificance] = useState(1)

  useEffect(() => {
    fetchJourneyData()
  }, [])

  const fetchJourneyData = async () => {
    try {
      setLoading(true)
      const [journeyRes, milestonesRes, phaseRes, fearRes] = await Promise.all([
        api.get('/api/v1/journey'),
        api.get('/api/v1/journey/milestones', {
          params: { min_significance: minSignificance },
        }),
        api.get('/api/v1/journey/phase-analysis'),
        api.get('/api/v1/psychology/fear-analysis').catch(() => ({ data: null })), // Fear analysis may not exist yet
      ])
      setJourneyData(journeyRes.data)
      setJourneyId(journeyRes.data.journey_id)  // ADDED: Store journey_id for mental blocks
      setMilestones(milestonesRes.data.milestones || [])
      setPhaseData(phaseRes.data)
      setPsychData(fearRes.data)
      
      // ADDED: Fetch mental blocks using the journey_id returned from journey endpoint
      if (journeyRes.data.journey_id) {
        try {
          const mentalBlocksRes = await api.get(
            `/api/v1/psychology/mental-blocks/${journeyRes.data.journey_id}`
          )
          console.log('Mental blocks loaded:', mentalBlocksRes.data)
        } catch (err) {
          console.debug('Mental blocks endpoint may not be ready yet:', err)
        }
      }
      
      setError(null)
    } catch (err) {
      console.error('Error fetching journey data:', err)
      setError('Failed to load your journey')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (activeTab === 'timeline') {
      fetchJourneyData()
    }
  }, [minSignificance])

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-950 text-white p-6">
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
    )
  }

  if (error) {
    return (
      <div className="min-h-screen bg-gray-950 text-white p-6">
        <div className="max-w-4xl mx-auto">
          <div className="bg-red-500/20 border border-red-500/50 rounded-lg p-4 text-red-400">
            {error}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="bg-gradient-to-b from-gray-900 to-gray-950 border-b border-gray-800 p-6">
        <div className="max-w-6xl mx-auto">
          <h1 className="text-4xl font-bold mb-2">Your Diving Journey</h1>
          <p className="text-gray-400">
            Your story written in water. Every attempt, every breakthrough, every moment that shaped you.
          </p>
        </div>
      </div>

      {/* Stats Bar */}
      {journeyData && (
        <div className="bg-gray-900 border-b border-gray-800 p-6">
          <div className="max-w-6xl mx-auto">
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
              <div>
                <div className="text-gray-400 text-sm mb-1">Total Dives</div>
                <div className="text-2xl font-bold">{journeyData.overview.total_dives}</div>
              </div>
              <div>
                <div className="text-gray-400 text-sm mb-1">Unique Dives</div>
                <div className="text-2xl font-bold">{journeyData.overview.unique_dive_combinations}</div>
              </div>
              <div>
                <div className="text-gray-400 text-sm mb-1">Training Days</div>
                <div className="text-2xl font-bold">{journeyData.overview.days_of_training}</div>
              </div>
              <div>
                <div className="text-gray-400 text-sm mb-1">Improvement</div>
                <div className={`text-2xl font-bold ${journeyData.growth.improvement > 0 ? 'text-green-400' : 'text-gray-400'}`}>
                  {journeyData.growth.improvement > 0 ? '+' : ''}{journeyData.growth.improvement.toFixed(2)}
                </div>
              </div>
              <div>
                <div className="text-gray-400 text-sm mb-1">Trajectory</div>
                <div className={`text-lg font-semibold ${
                  journeyData.growth.trajectory === 'improving' ? 'text-green-400' :
                  journeyData.growth.trajectory === 'plateauing' ? 'text-amber-400' :
                  'text-red-400'
                }`}>
                  {journeyData.growth.trajectory}
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="border-b border-gray-800 bg-gray-900/50 overflow-x-auto">
        <div className="max-w-6xl mx-auto px-6">
          <div className="flex gap-8 whitespace-nowrap">
            <button
              onClick={() => setActiveTab('narrative')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'narrative'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Your Story
            </button>
            <button
              onClick={() => setActiveTab('dd-progression')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'dd-progression'
                  ? 'border-yellow-400 text-yellow-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              DD Progression
            </button>
            <button
              onClick={() => setActiveTab('timeline')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'timeline'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Milestones
            </button>
            <button
              onClick={() => setActiveTab('phases')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'phases'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Phase Analysis
            </button>
            <button
              onClick={() => setActiveTab('psychology')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'psychology'
                  ? 'border-purple-400 text-purple-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Psychology
            </button>
            <button
              onClick={() => setActiveTab('avoided')}
              className={`py-4 px-2 border-b-2 font-medium transition-colors ${
                activeTab === 'avoided'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Patterns
            </button>
          </div>
        </div>
      </div>

      {/* Content Area */}
      <div className="max-w-7xl mx-auto p-6">
        <JourneyWithSync onSyncComplete={() => fetchJourneyData()}>
        {activeTab === 'narrative' && journeyData && (
          <JourneyNarrative data={journeyData} />
        )}

        {activeTab === 'timeline' && (
          <>
            <div className="mb-6 flex items-center justify-between">
              <h2 className="text-2xl font-bold">Milestone Timeline</h2>
              <div className="flex items-center gap-3">
                <label className="text-sm text-gray-400">Min Significance:</label>
                <select
                  value={minSignificance}
                  onChange={(e) => setMinSignificance(parseInt(e.target.value))}
                  className="bg-gray-800 text-white rounded px-3 py-1 border border-gray-700 text-sm"
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

        {activeTab === 'phases' && phaseData && (
          <div className="space-y-6">
            <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
              <h2 className="text-2xl font-bold mb-2">Two-Phase Dive Analysis</h2>
              <p className="text-gray-400 mb-4">
                Separates takeoff quality from landing quality to identify specific strengths and areas for improvement.
              </p>

              {/* Summary Stats */}
              <div className="grid grid-cols-4 gap-4 mb-6 pb-6 border-b border-gray-800">
                <div>
                  <div className="text-gray-400 text-sm mb-1">Total Dives</div>
                  <div className="text-2xl font-bold">{phaseData.summary?.total_dives || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm mb-1">Two-Phase Format</div>
                  <div className="text-2xl font-bold text-cyan-400">{phaseData.summary?.two_phase_dives || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm mb-1">Legacy Format</div>
                  <div className="text-2xl font-bold text-blue-400">{phaseData.summary?.legacy_dives || 0}</div>
                </div>
                <div>
                  <div className="text-gray-400 text-sm mb-1">New Format %</div>
                  <div className="text-2xl font-bold text-green-400">{phaseData.summary?.percentage_new_format || 0}%</div>
                </div>
              </div>

              {/* Phase 1 Analysis */}
              <div className="mb-8">
                <div className="mb-4">
                  <h3 className="text-xl font-bold text-cyan-400 mb-2">Phase 1: Hurdle + Flight (Takeoff)</h3>
                  <p className="text-gray-400 text-sm mb-3">{phaseData.phase1_analysis?.description}</p>
                  <div className="text-2xl font-bold mb-2">Average Score: {phaseData.phase1_analysis?.average}</div>
                </div>

                {/* Phase 1 Distribution */}
                <div className="grid grid-cols-5 gap-2">
                  {phaseData.phase1_analysis?.distribution && Object.entries(phaseData.phase1_analysis.distribution).map(([score, count]) => (
                    <div key={score} className="bg-gray-800 rounded p-3 border border-gray-700 text-center">
                      <div className="text-lg font-bold text-cyan-400">{score}</div>
                      <div className="text-gray-400 text-xs">{count} dives</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Phase 2 Analysis */}
              <div className="mb-8">
                <div className="mb-4">
                  <h3 className="text-xl font-bold text-cyan-400 mb-2">Phase 2: Opening + Entry (Landing)</h3>
                  <p className="text-gray-400 text-sm mb-3">{phaseData.phase2_analysis?.description}</p>
                  <div className="text-2xl font-bold mb-2">Average Score: {phaseData.phase2_analysis?.average}</div>
                </div>

                {/* Phase 2 Distribution */}
                <div className="grid grid-cols-5 gap-2">
                  {phaseData.phase2_analysis?.distribution && Object.entries(phaseData.phase2_analysis.distribution).map(([score, count]) => (
                    <div key={score} className="bg-gray-800 rounded p-3 border border-gray-700 text-center">
                      <div className="text-lg font-bold text-cyan-400">{score}</div>
                      <div className="text-gray-400 text-xs">{count} dives</div>
                    </div>
                  ))}
                </div>
              </div>

              {/* Phase Combinations */}
              {phaseData.phase_combinations?.distribution && (
                <div className="mb-8">
                  <h3 className="text-xl font-bold text-cyan-400 mb-4">Most Common Phase Combinations</h3>
                  <div className="space-y-2">
                    {Object.entries(phaseData.phase_combinations.distribution)
                      .sort(([, a], [, b]) => (b as number) - (a as number))
                      .slice(0, 5)
                      .map(([combo, count]) => (
                        <div key={combo} className="flex items-center justify-between bg-gray-800 rounded p-3 border border-gray-700">
                          <div className="font-mono text-cyan-400">{combo}</div>
                          <div className="text-gray-400">{count} dives</div>
                        </div>
                      ))
                    }
                  </div>
                </div>
              )}

              {/* Coaching Insights */}
              {phaseData.coaching_insights && phaseData.coaching_insights.length > 0 && (
                <div>
                  <h3 className="text-xl font-bold text-green-400 mb-4">Coaching Insights</h3>
                  <div className="space-y-3">
                    {phaseData.coaching_insights.map((insight: any, idx: number) => (
                      <div key={idx} className="bg-green-500/10 border border-green-500/30 rounded p-4">
                        <div className="font-bold text-green-400 mb-1">{insight.pattern}</div>
                        <p className="text-gray-300 text-sm">{insight.coaching}</p>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Recommendation */}
              {phaseData.recommendation && (
                <div className="mt-6 bg-blue-500/10 border border-blue-500/30 rounded p-4">
                  <p className="text-blue-300">{phaseData.recommendation}</p>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'dd-progression' && journeyData && (
          <div className="space-y-6">
            <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
              <h2 className="text-2xl font-bold mb-2">Your Difficulty Progression</h2>
              <p className="text-gray-400 mb-6">
                Track your journey from simpler to more complex dives. Each breakthrough represents growth and confidence.
              </p>

              {journeyData.dd_progression ? (
                <>
                  {/* DD Stats */}
                  <div className="grid grid-cols-3 gap-4 mb-8 pb-8 border-b border-gray-800">
                    <div className="bg-gray-800 rounded p-4 border border-gray-700">
                      <div className="text-gray-400 text-sm mb-2">Current Max DD</div>
                      <div className="text-3xl font-bold text-yellow-400">
                        {journeyData.dd_progression.current_max.toFixed(1)}
                      </div>
                    </div>
                    <div className="bg-gray-800 rounded p-4 border border-gray-700">
                      <div className="text-gray-400 text-sm mb-2">Highest Achieved</div>
                      <div className="text-3xl font-bold text-orange-400">
                        {journeyData.dd_progression.highest_achieved.toFixed(1)}
                      </div>
                    </div>
                    <div className="bg-gray-800 rounded p-4 border border-gray-700">
                      <div className="text-gray-400 text-sm mb-2">Progress Range</div>
                      <div className="text-2xl font-bold text-green-400">
                        +{(journeyData.dd_progression.highest_achieved - 1.2).toFixed(1)}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">(from baseline 1.2)</div>
                    </div>
                  </div>

                  {/* Monthly Progression */}
                  <div>
                    <h3 className="text-xl font-bold text-yellow-400 mb-4">Monthly Progression</h3>
                    <div className="space-y-3">
                      {journeyData.dd_progression.months.map((month, idx) => (
                        <div key={idx} className="bg-gray-800 rounded p-4 border border-gray-700">
                          <div className="flex items-center justify-between mb-2">
                            <div className="font-bold text-cyan-400">{month.month}</div>
                            <div className="text-right">
                              <div className="text-2xl font-bold text-yellow-400">{month.max_dd.toFixed(1)}</div>
                              <div className="text-xs text-gray-400">{month.attempts} attempts</div>
                            </div>
                          </div>

                          {/* Breakthroughs */}
                          {month.breakthroughs && month.breakthroughs.length > 0 && (
                            <div className="mt-3 pt-3 border-t border-gray-700">
                              <div className="flex flex-wrap gap-2">
                                {month.breakthroughs.map((bt, btIdx) => (
                                  <span
                                    key={btIdx}
                                    className="text-xs bg-green-500/20 text-green-400 px-2 py-1 rounded"
                                  >
                                    🎉 {bt}
                                  </span>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Progress bar */}
                          <div className="mt-3 h-2 bg-gray-700 rounded-full overflow-hidden">
                            <div
                              className="h-full bg-gradient-to-r from-yellow-400 to-orange-400 rounded-full"
                              style={{ width: `${Math.min((month.max_dd / 4.1) * 100, 100)}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* DD Categories */}
                  <div className="mt-8 pt-8 border-t border-gray-800">
                    <h3 className="text-xl font-bold mb-4">Difficulty Categories</h3>
                    <div className="grid grid-cols-4 gap-4">
                      <div className="bg-green-500/10 border border-green-500/30 rounded p-4 text-center">
                        <div className="text-2xl font-bold text-green-400 mb-1">🟢</div>
                        <div className="text-sm text-gray-400 mb-2">Easy</div>
                        <div className="text-xs text-gray-500">1.2 - 1.8</div>
                      </div>
                      <div className="bg-yellow-500/10 border border-yellow-500/30 rounded p-4 text-center">
                        <div className="text-2xl font-bold text-yellow-400 mb-1">🟡</div>
                        <div className="text-sm text-gray-400 mb-2">Medium</div>
                        <div className="text-xs text-gray-500">1.9 - 2.5</div>
                      </div>
                      <div className="bg-orange-500/10 border border-orange-500/30 rounded p-4 text-center">
                        <div className="text-2xl font-bold text-orange-400 mb-1">🟠</div>
                        <div className="text-sm text-gray-400 mb-2">Hard</div>
                        <div className="text-xs text-gray-500">2.6 - 3.3</div>
                      </div>
                      <div className="bg-red-500/10 border border-red-500/30 rounded p-4 text-center">
                        <div className="text-2xl font-bold text-red-400 mb-1">🔴</div>
                        <div className="text-sm text-gray-400 mb-2">Expert</div>
                        <div className="text-xs text-gray-500">3.4 - 4.1</div>
                      </div>
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center py-8 text-gray-400">
                  No DD progression data available yet. As you log more dives, your progression will be tracked here.
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'psychology' && (
          <div className="space-y-6">
            {/* Mental Block Analysis */}
            {journeyId && (
              <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
                <h2 className="text-2xl font-bold mb-4">🧠 Mental Block Analysis</h2>
                <MentalBlockAnalysis journeyId={journeyId} />
              </div>
            )}

            {/* Mental Block Detection (Legacy) */}
            <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
              <h3 className="text-xl font-bold text-yellow-400 mb-4">Quick Status Check</h3>
              <MentalBlockIndicator />
            </div>

            <div className="bg-gray-900 rounded-lg p-6 border border-gray-800">
              <h2 className="text-2xl font-bold mb-2">🧠 Your Psychological Profile</h2>
              <p className="text-gray-400 mb-6">
                Understanding your emotions, confidence, and mental blocks helps you grow as a diver.
              </p>

              {journeyData?.psychological ? (
                <>
                  {/* Mental Health Indicators */}
                  <div className="grid grid-cols-2 md:grid-cols-3 gap-4 mb-8 pb-8 border-b border-gray-800">
                    <div className="bg-purple-500/10 border border-purple-500/30 rounded p-4">
                      <div className="text-gray-400 text-sm mb-2">Mental Blocks Detected</div>
                      <div className="text-2xl font-bold text-purple-400">
                        {journeyData.psychological.mental_blocks_detected || 0}
                      </div>
                    </div>
                    <div className="bg-blue-500/10 border border-blue-500/30 rounded p-4">
                      <div className="text-gray-400 text-sm mb-2">Fear vs Difficulty</div>
                      <div className="text-2xl font-bold text-blue-400">
                        {journeyData.psychological.fear_coefficient ? journeyData.psychological.fear_coefficient.toFixed(2) : '1.0'}
                      </div>
                      <div className="text-xs text-gray-500 mt-1">Coefficient ratio</div>
                    </div>
                    <div className="bg-green-500/10 border border-green-500/30 rounded p-4">
                      <div className="text-gray-400 text-sm mb-2">Confidence Trend</div>
                      <div className={`text-2xl font-bold ${
                        journeyData.psychological.confidence_trend === 'improving' ? 'text-green-400' :
                        journeyData.psychological.confidence_trend === 'stable' ? 'text-yellow-400' :
                        'text-red-400'
                      }`}>
                        {journeyData.psychological.confidence_trend ?
                          journeyData.psychological.confidence_trend.charAt(0).toUpperCase() +
                          journeyData.psychological.confidence_trend.slice(1)
                          : 'Stable'}
                      </div>
                    </div>
                  </div>

                  {/* Mental Blocks Alert */}
                  {journeyData.psychological.mental_blocks_detected > 0 && (
                    <div className="bg-yellow-500/10 border border-yellow-500/30 rounded p-4 mb-6">
                      <div className="text-yellow-400 font-bold mb-2">⚠️ Mental Block Detected</div>
                      <p className="text-gray-300 text-sm">
                        You've been attempting the same maximum difficulty for 3+ months. This is a natural plateau!
                        Consider:
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
                  <div className="bg-gray-800 rounded p-4 border border-gray-700">
                    <h3 className="text-lg font-bold text-green-400 mb-3">Your Growth Arc</h3>
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-gray-400">First Month Avg Performance</span>
                        <span className="text-white font-bold">{journeyData.growth.first_month_average.toFixed(2)} / 4.0</span>
                      </div>
                      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-cyan-500 to-blue-500"
                          style={{ width: `${(journeyData.growth.first_month_average / 4.0) * 100}%` }}
                        />
                      </div>

                      <div className="flex items-center justify-between mt-4">
                        <span className="text-gray-400">Latest Month Avg Performance</span>
                        <span className="text-white font-bold">{journeyData.growth.last_month_average.toFixed(2)} / 4.0</span>
                      </div>
                      <div className="h-2 bg-gray-700 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-gradient-to-r from-green-500 to-emerald-500"
                          style={{ width: `${(journeyData.growth.last_month_average / 4.0) * 100}%` }}
                        />
                      </div>

                      <div className="mt-4 p-3 bg-blue-500/10 border border-blue-500/30 rounded">
                        <div className="text-blue-400 font-bold">Overall Improvement</div>
                        <div className="text-white text-lg">
                          {journeyData.growth.improvement > 0 ? '+' : ''}{journeyData.growth.improvement.toFixed(2)} points
                        </div>
                        <div className="text-gray-400 text-sm mt-1">
                          {journeyData.growth.trajectory === 'improving' ? '📈 You\'re getting better!' :
                           journeyData.growth.trajectory === 'plateauing' ? '➡️ Holding steady' :
                           '📉 Room for growth'}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Emotional State Placeholder */}
                  <div className="bg-gray-800 rounded p-4 border border-gray-700 mt-4">
                    <h3 className="text-lg font-bold text-purple-400 mb-3">Emotional Tracking</h3>
                    <p className="text-gray-400 text-sm mb-3">
                      Ready to start logging your emotional state? This helps us understand your confidence patterns and identify mental blocks.
                    </p>
                    <div className="inline-block px-4 py-2 bg-purple-600 hover:bg-purple-700 text-white rounded text-sm font-medium cursor-pointer transition">
                      Start Tracking Emotions
                    </div>
                  </div>
                </>
              ) : (
                <div className="text-center py-8 text-gray-400">
                  <div className="animate-pulse">Loading your psychological profile...</div>
                </div>
              )}
            </div>
          </div>
        )}

        {activeTab === 'avoided' && (
          <AvoidedDives />
        )}
        </JourneyWithSync>
      </div>
    </div>
  )
}

export default Journey
