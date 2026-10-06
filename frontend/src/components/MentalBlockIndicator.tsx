import React, { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api } from '../services/api'
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight } from 'lucide-react'

interface MentalBlock {
  type: 'dd_plateau' | 'repeated_failure' | 'avoided_dive'
  description: string
  dives_affected: string[]
  duration_months: number
  recommendations: string[]
}

function MentalBlockIndicator() {
  const { t } = useTranslation()
  const [blocks, setBlocks] = useState<MentalBlock[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<string | null>(null)

  useEffect(() => {
    fetchMentalBlocks()
  }, [])

  const fetchMentalBlocks = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/journey/mental-blocks')
      setBlocks(response.data.blocks || [])
      setError(null)
    } catch (err) {
      // Mental blocks endpoint may not exist yet - silently handle
      console.debug('Mental blocks data not available yet')
      setBlocks([])
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="animate-pulse bg-app-panel rounded-lg p-4 h-24 border border-app"></div>
    )
  }

  if (blocks.length === 0) {
    return (
      <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-4">
        <div className="flex items-center gap-2 font-bold text-green-400"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />{t('mentalBlock.none')}</div>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {blocks.map((block, idx) => {
        const blockKey = `block-${idx}`
        const isExpanded = expanded === blockKey

        return (
          <div
            key={blockKey}
            className="bg-yellow-500/10 border border-yellow-500/30 rounded-lg overflow-hidden"
          >
            <button
              onClick={() => setExpanded(isExpanded ? null : blockKey)}
              className="w-full p-4 flex items-start justify-between hover:bg-yellow-500/5 transition-colors"
            >
              <div className="text-left">
                <div className="text-yellow-400 font-bold flex items-center gap-2">
                  <AlertTriangle className="h-4 w-4" aria-hidden="true" />
                  {block.type === 'dd_plateau' && t('mentalBlock.ddPlateau')}
                  {block.type === 'repeated_failure' && t('mentalBlock.repeatedFailure')}
                  {block.type === 'avoided_dive' && t('mentalBlock.avoidedDive')}
                </div>
                <p className="text-yellow-300 text-sm mt-1">{block.description}</p>
                <div className="text-xs text-app-muted mt-2">
                  {t('mentalBlock.summary', {
                    months: t('mentalBlock.months', { count: block.duration_months }),
                    dives: t('mentalBlock.dives', { count: block.dives_affected.length }),
                  })}
                </div>
              </div>
              <div className="text-xl text-yellow-400 ml-4">
                {isExpanded ? <ChevronDown className="h-5 w-5" /> : <ChevronRight className="h-5 w-5" />}
              </div>
            </button>

            {isExpanded && (
              <div className="bg-yellow-500/5 border-t border-yellow-500/30 p-4 space-y-4">
                {/* Affected Dives */}
                <div>
                  <h4 className="text-sm font-bold text-yellow-400 mb-2">{t('mentalBlock.affectedDives')}</h4>
                  <div className="flex flex-wrap gap-2">
                    {block.dives_affected.map((dive) => (
                      <span
                        key={dive}
                        className="text-xs bg-yellow-500/20 text-yellow-300 px-3 py-1 rounded"
                      >
                        {dive}
                      </span>
                    ))}
                  </div>
                </div>

                {/* Recommendations */}
                <div>
                  <h4 className="text-sm font-bold text-green-400 mb-2">{t('mentalBlock.recoveryPlan')}</h4>
                  <div className="space-y-2">
                    {block.recommendations.map((rec, recIdx) => (
                      <div
                        key={recIdx}
                        className="text-sm text-app-text flex items-start gap-2"
                      >
                        <span className="text-green-400 font-bold mt-0.5">•</span>
                        <span>{rec}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Action Button */}
                <div className="flex gap-2">
                  <button
                    onClick={() => fetchMentalBlocks()}
                    className="flex-1 py-2 px-3 bg-app-panel-elevated border border-app-strong text-app-text rounded text-sm font-medium transition-colors"
                  >
                    {t('mentalBlock.checkProgress')}
                  </button>
                  <button
                    onClick={() => setExpanded(null)}
                    className="flex-1 py-2 px-3 bg-app-panel border border-app hover:text-app-text text-app-text rounded text-sm font-medium transition-colors"
                  >
                    {t('mentalBlock.dismiss')}
                  </button>
                </div>
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

export default MentalBlockIndicator
