import React, { useEffect, useState } from 'react'
import { api } from '../services/api'

interface EventType {
  code: string
  name: string
  heights: string[]
  min_dives: number
  max_dives: number
  mandatory_groups: number[]
}

interface Participant {
  name: string
  level: 'beginner' | 'intermediate' | 'advanced' | 'elite'
}

interface CompetitionEventSetupProps {
  onEventCreated?: (eventId: number) => void
}

function CompetitionEventSetup({ onEventCreated }: CompetitionEventSetupProps) {
  const [step, setStep] = useState<'type' | 'height' | 'participants' | 'confirm'>(
    'type'
  )
  const [eventType, setEventType] = useState<EventType | null>(null)
  const [height, setHeight] = useState<string>('')
  const [participants, setParticipants] = useState<Participant[]>([])
  const [newParticipantName, setNewParticipantName] = useState('')
  const [newParticipantLevel, setNewParticipantLevel] = useState<
    'beginner' | 'intermediate' | 'advanced' | 'elite'
  >('intermediate')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const eventTypes: EventType[] = [
    {
      code: 'sprint',
      name: 'Sprint Dive Series',
      heights: ['1m', '3m'],
      min_dives: 3,
      max_dives: 6,
      mandatory_groups: [1, 2],
    },
    {
      code: 'platform',
      name: 'Platform Challenge',
      heights: ['5m', '7.5m', '10m'],
      min_dives: 4,
      max_dives: 8,
      mandatory_groups: [1, 2, 3],
    },
    {
      code: 'fina_1m',
      name: 'FINA 1m Springboard',
      heights: ['1m'],
      min_dives: 6,
      max_dives: 6,
      mandatory_groups: [1, 2, 3, 4, 5, 6],
    },
    {
      code: 'fina_3m',
      name: 'FINA 3m Springboard',
      heights: ['3m'],
      min_dives: 6,
      max_dives: 6,
      mandatory_groups: [1, 2, 3, 4, 5, 6],
    },
    {
      code: 'fina_10m',
      name: 'FINA 10m Platform',
      heights: ['10m'],
      min_dives: 6,
      max_dives: 6,
      mandatory_groups: [1, 2, 3, 4, 5, 6],
    },
    {
      code: 'custom',
      name: 'Custom Event',
      heights: ['1m', '3m', '5m', '7.5m', '10m'],
      min_dives: 1,
      max_dives: 12,
      mandatory_groups: [],
    },
  ]

  const addParticipant = () => {
    if (!newParticipantName.trim()) {
      setError('Please enter a name')
      return
    }

    setParticipants([
      ...participants,
      { name: newParticipantName, level: newParticipantLevel },
    ])
    setNewParticipantName('')
    setError(null)
  }

  const removeParticipant = (index: number) => {
    setParticipants(participants.filter((_, i) => i !== index))
  }

  const handleCreateEvent = async () => {
    if (!eventType || !height || participants.length === 0) {
      setError('Please complete all steps')
      return
    }

    try {
      setLoading(true)
      const response = await api.post('/api/v1/events', {
        event_code: eventType.code,
        event_type: eventType.name,
        height: height,
        dive_count: eventType.min_dives,
        mandatory_groups: eventType.mandatory_groups,
      })

      const eventId = response.data.id

      // Add participants
      for (const participant of participants) {
        await api.post(`/api/v1/events/${eventId}/participants`, {
          name: participant.name,
          level: participant.level,
        })
      }

      if (onEventCreated) {
        onEventCreated(eventId)
      }

      setError(null)
      alert('Event created successfully!')
    } catch (err) {
      console.error('Error creating event:', err)
      setError('Failed to create event. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="max-w-2xl mx-auto">
      {/* Progress Bar */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center font-bold ${
                step === 'type' || ['height', 'participants', 'confirm'].includes(step)
                  ? 'bg-green-500/30 text-green-400'
                  : 'bg-gray-600/30 text-gray-400'
              }`}
            >
              1
            </div>
            <div className="text-sm font-semibold">Event Type</div>
          </div>

          <div className="flex-1 h-1 bg-gray-700 mx-2"></div>

          <div className="flex items-center gap-2">
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center font-bold ${
                step === 'height' || ['participants', 'confirm'].includes(step)
                  ? 'bg-green-500/30 text-green-400'
                  : 'bg-gray-600/30 text-gray-400'
              }`}
            >
              2
            </div>
            <div className="text-sm font-semibold">Height</div>
          </div>

          <div className="flex-1 h-1 bg-gray-700 mx-2"></div>

          <div className="flex items-center gap-2">
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center font-bold ${
                step === 'participants' || step === 'confirm'
                  ? 'bg-green-500/30 text-green-400'
                  : 'bg-gray-600/30 text-gray-400'
              }`}
            >
              3
            </div>
            <div className="text-sm font-semibold">Participants</div>
          </div>

          <div className="flex-1 h-1 bg-gray-700 mx-2"></div>

          <div className="flex items-center gap-2">
            <div
              className={`w-10 h-10 rounded-full flex items-center justify-center font-bold ${
                step === 'confirm'
                  ? 'bg-green-500/30 text-green-400'
                  : 'bg-gray-600/30 text-gray-400'
              }`}
            >
              4
            </div>
            <div className="text-sm font-semibold">Confirm</div>
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-6">
          <p className="text-red-400 text-sm">{error}</p>
        </div>
      )}

      {/* Step 1: Event Type */}
      {step === 'type' && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold mb-4">Select Event Type</h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {eventTypes.map((et) => (
              <button
                key={et.code}
                onClick={() => {
                  setEventType(et)
                  setStep('height')
                }}
                className={`p-4 rounded-lg border text-left transition-colors ${
                  eventType?.code === et.code
                    ? 'bg-cyan-500/20 border-cyan-500/50'
                    : 'bg-gray-800/50 border-gray-700 hover:bg-gray-800'
                }`}
              >
                <p className="font-bold text-gray-100">{et.name}</p>
                <p className="text-xs text-gray-400 mt-1">
                  {et.min_dives}-{et.max_dives} dives
                </p>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Step 2: Height */}
      {step === 'height' && eventType && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold mb-4">Select Height</h2>
          <p className="text-gray-400 mb-4">
            Available for {eventType.name}
          </p>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
            {eventType.heights.map((h) => (
              <button
                key={h}
                onClick={() => {
                  setHeight(h)
                  setStep('participants')
                }}
                className={`p-4 rounded-lg border font-semibold transition-colors ${
                  height === h
                    ? 'bg-cyan-500/20 border-cyan-500/50 text-cyan-400'
                    : 'bg-gray-800/50 border-gray-700 hover:bg-gray-800 text-gray-300'
                }`}
              >
                {h}
              </button>
            ))}
          </div>
          <button
            onClick={() => setStep('type')}
            className="mt-6 px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300"
          >
            ← Back
          </button>
        </div>
      )}

      {/* Step 3: Participants */}
      {step === 'participants' && eventType && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold mb-4">Add Participants</h2>
          <p className="text-gray-400 mb-4">
            {eventType.name} from {height}
          </p>

          {/* Add Participant Form */}
          <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-4 space-y-3 mb-4">
            <div>
              <label className="block text-sm text-gray-400 mb-1">Name</label>
              <input
                type="text"
                value={newParticipantName}
                onChange={(e) => setNewParticipantName(e.target.value)}
                placeholder="Enter participant name"
                className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white placeholder-gray-500"
              />
            </div>
            <div>
              <label className="block text-sm text-gray-400 mb-1">Level</label>
              <select
                value={newParticipantLevel}
                onChange={(e) =>
                  setNewParticipantLevel(e.target.value as typeof newParticipantLevel)
                }
                className="w-full bg-gray-900 border border-gray-700 rounded px-3 py-2 text-white"
              >
                <option value="beginner">Beginner</option>
                <option value="intermediate">Intermediate</option>
                <option value="advanced">Advanced</option>
                <option value="elite">Elite</option>
              </select>
            </div>
            <button
              onClick={addParticipant}
              className="w-full bg-cyan-500/30 hover:bg-cyan-500/40 text-cyan-400 rounded py-2 font-semibold transition-colors"
            >
              + Add Participant
            </button>
          </div>

          {/* Participants List */}
          {participants.length > 0 && (
            <div className="space-y-2">
              <p className="text-sm font-semibold text-gray-400">
                {participants.length} participant{participants.length !== 1 ? 's' : ''}
              </p>
              {participants.map((p, idx) => (
                <div
                  key={idx}
                  className="flex items-center justify-between bg-gray-800/50 border border-gray-700 rounded p-3"
                >
                  <div>
                    <p className="font-semibold text-gray-200">{p.name}</p>
                    <p className="text-xs text-gray-500 capitalize">{p.level}</p>
                  </div>
                  <button
                    onClick={() => removeParticipant(idx)}
                    className="text-red-400 hover:text-red-300"
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Navigation */}
          <div className="flex gap-3 mt-6">
            <button
              onClick={() => setStep('height')}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300"
            >
              ← Back
            </button>
            <button
              onClick={() => setStep('confirm')}
              disabled={participants.length === 0}
              className="flex-1 px-4 py-2 bg-cyan-500/30 hover:bg-cyan-500/40 text-cyan-400 rounded text-sm font-semibold disabled:opacity-50 transition-colors"
            >
              Next →
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Confirm */}
      {step === 'confirm' && eventType && (
        <div className="space-y-4">
          <h2 className="text-2xl font-bold mb-4">Review Event Details</h2>

          {/* Summary */}
          <div className="bg-gradient-to-r from-cyan-500/10 to-blue-500/10 border border-cyan-500/30 rounded-lg p-6 space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <p className="text-gray-500 text-sm">Event Type</p>
                <p className="text-lg font-bold text-cyan-400">{eventType.name}</p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Height</p>
                <p className="text-lg font-bold text-cyan-400">{height}</p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Dive Count</p>
                <p className="text-lg font-bold text-cyan-400">
                  {eventType.min_dives}-{eventType.max_dives}
                </p>
              </div>
              <div>
                <p className="text-gray-500 text-sm">Participants</p>
                <p className="text-lg font-bold text-cyan-400">{participants.length}</p>
              </div>
            </div>
          </div>

          {/* Participants Summary */}
          <div className="space-y-2">
            <p className="font-semibold text-gray-400">Participants</p>
            {participants.map((p, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between bg-gray-800/50 rounded p-3 border border-gray-700"
              >
                <span className="font-semibold text-gray-200">{p.name}</span>
                <span className="text-xs text-gray-500 capitalize">{p.level}</span>
              </div>
            ))}
          </div>

          {/* Navigation */}
          <div className="flex gap-3 mt-6">
            <button
              onClick={() => setStep('participants')}
              className="px-4 py-2 bg-gray-700 hover:bg-gray-600 rounded text-sm text-gray-300"
            >
              ← Back
            </button>
            <button
              onClick={handleCreateEvent}
              disabled={loading}
              className="flex-1 px-4 py-2 bg-green-500/30 hover:bg-green-500/40 text-green-400 rounded text-sm font-semibold disabled:opacity-50 transition-colors"
            >
              {loading ? 'Creating...' : '✓ Create Event'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default CompetitionEventSetup
