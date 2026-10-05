import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { milestoneDisplay } from '../i18n/milestones'
import { Star, Award, Zap, Trophy, X } from 'lucide-react'

interface MilestoneAlert {
  id: string
  type: string
  title: string
  narrative: string
  icon: React.ReactNode
}

/**
 * MilestoneNotifier Component
 * Shows celebratory notifications when milestones are detected
 */
export const MilestoneNotifier: React.FC<{ maxVisible?: number }> = ({
  maxVisible = 3,
}) => {
  const { t } = useTranslation()
  const { recentMilestones, removeMilestone } = useSyncStatus()
  const [alerts, setAlerts] = useState<MilestoneAlert[]>([])

  // Convert milestones to alerts
  useEffect(() => {
    const newAlerts = recentMilestones.slice(0, maxVisible).map((milestone, idx) => {
      let icon: React.ReactNode

      switch (milestone.type) {
        case 'first_dive':
          icon = <Star className="w-8 h-8" />
          break
        case 'height_milestone':
          icon = <Trophy className="w-8 h-8" />
          break
        case 'consistency_milestone':
          icon = <Zap className="w-8 h-8" />
          break
        case 'dive_mastery':
          icon = <Award className="w-8 h-8" />
          break
        default:
          icon = <Star className="w-8 h-8" />
      }

      const display = milestoneDisplay(milestone)
      return {
        id: `milestone-${milestone.date}-${idx}`,
        type: milestone.type,
        title: display.title,
        narrative: display.narrative,
        icon,
      }
    })

    setAlerts(newAlerts)
  }, [recentMilestones, maxVisible])

  const handleDismiss = (idx: number) => {
    removeMilestone(idx)
  }

  return (
    <div className="fixed top-20 right-6 z-40 space-y-4 pointer-events-none">
      {alerts.map((alert, idx) => (
        <div key={alert.id} className="pointer-events-auto">
          <div className="rounded-lg p-4 border border-app-accent bg-app-panel shadow-lg max-w-sm">
            <div className="flex items-start gap-4">
              <div className="bg-app-accent-soft text-app-accent p-2 rounded-lg flex-shrink-0">
                {alert.icon}
              </div>

              <div className="flex-1">
                <h4 className="font-bold text-lg mb-1 text-app-text">{alert.title}</h4>
                <p className="text-sm text-app-muted">{alert.narrative}</p>
              </div>

              <button
                onClick={() => handleDismiss(idx)}
                className="text-app-muted hover:text-app-text flex-shrink-0"
                aria-label={t('milestones.dismiss')}
              >
                <X className="w-5 h-5" />
              </button>
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default MilestoneNotifier
