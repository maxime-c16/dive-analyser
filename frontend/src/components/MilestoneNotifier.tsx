import React, { useState, useEffect } from 'react'
import { useSyncStatus } from '../hooks/useSyncStatus'
import { Star, Award, Zap, Trophy, X } from 'lucide-react'

interface MilestoneAlert {
  id: string
  type: string
  title: string
  narrative: string
  icon: React.ReactNode
  color: string
}

/**
 * MilestoneNotifier Component
 * Shows celebratory notifications when milestones are detected
 */
export const MilestoneNotifier: React.FC<{ maxVisible?: number }> = ({
  maxVisible = 3,
}) => {
  const { recentMilestones, removeMilestone } = useSyncStatus()
  const [alerts, setAlerts] = useState<MilestoneAlert[]>([])

  // Convert milestones to alerts
  useEffect(() => {
    const newAlerts = recentMilestones.slice(0, maxVisible).map((milestone, idx) => {
      let icon: React.ReactNode
      let color: string

      switch (milestone.type) {
        case 'first_dive':
          icon = <Star className="w-8 h-8" />
          color = 'from-yellow-400 to-amber-400'
          break
        case 'height_milestone':
          icon = <Trophy className="w-8 h-8" />
          color = 'from-purple-400 to-pink-400'
          break
        case 'consistency_milestone':
          icon = <Zap className="w-8 h-8" />
          color = 'from-cyan-400 to-blue-400'
          break
        case 'dive_mastery':
          icon = <Award className="w-8 h-8" />
          color = 'from-green-400 to-emerald-400'
          break
        default:
          icon = <Star className="w-8 h-8" />
          color = 'from-blue-400 to-cyan-400'
      }

      return {
        id: `milestone-${milestone.date}-${idx}`,
        type: milestone.type,
        title: milestone.title,
        narrative: milestone.narrative,
        icon,
        color,
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
        <div
          key={alert.id}
          className="animate-in fade-in slide-in-from-top-2 pointer-events-auto"
        >
          <div
            className={`rounded-lg p-4 border border-2 border-transparent bg-gradient-to-br ${alert.color} bg-opacity-10 shadow-lg max-w-sm`}
          >
            <div className="flex items-start gap-4">
              <div className={`bg-gradient-to-br ${alert.color} p-2 rounded-lg flex-shrink-0`}>
                {alert.icon}
              </div>

              <div className="flex-1">
                <h4 className="font-bold text-lg mb-1">{alert.title}</h4>
                <p className="text-sm text-gray-200">{alert.narrative}</p>
              </div>

              <button
                onClick={() => handleDismiss(idx)}
                className="text-gray-400 hover:text-gray-300 flex-shrink-0"
                aria-label="Dismiss milestone"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Celebratory animation background */}
            <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-lg">
              {[...Array(3)].map((_, i) => (
                <div
                  key={i}
                  className="absolute animate-ping opacity-75"
                  style={{
                    width: '4px',
                    height: '4px',
                    borderRadius: '50%',
                    left: `${25 + i * 25}%`,
                    top: `${25 + i * 25}%`,
                    animationDelay: `${i * 0.2}s`,
                  }}
                />
              ))}
            </div>
          </div>
        </div>
      ))}
    </div>
  )
}

export default MilestoneNotifier
