import React, { useEffect, useState } from 'react'
import { api } from '../services/api'
import CompetitionEventSetup from '../components/CompetitionEventSetup'
import CompetitionScoring from '../components/CompetitionScoring'
import CompetitionResults from '../components/CompetitionResults'
import ComplianceDashboard from '../components/ComplianceDashboard'

interface Event {
  id: number
  event_code: string
  event_type: string
  height: string
  dive_count: number
  status: 'setup' | 'active' | 'finished'
  created_at: string
}

type Tab = 'create' | 'active' | 'results' | 'compliance'

function CompetitionHub() {
  const [activeTab, setActiveTab] = useState<Tab>('create')
  const [events, setEvents] = useState<Event[]>([])
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchEvents()
  }, [])

  const fetchEvents = async () => {
    try {
      setLoading(true)
      const response = await api.get('/api/v1/events')
      setEvents(response.data.events || [])
      setError(null)
    } catch (err) {
      console.error('Error fetching events:', err)
      setError('Failed to load events')
    } finally {
      setLoading(false)
    }
  }

  const handleEventCreated = (eventId: number) => {
    setSelectedEventId(eventId)
    setActiveTab('active')
    fetchEvents()
  }

  const selectedEvent = events.find((e) => e.id === selectedEventId)

  return (
    <div className="min-h-screen bg-gray-950 text-white">
      {/* Header */}
      <div className="bg-gradient-to-b from-gray-900 to-gray-950 border-b border-gray-800 p-6">
        <div className="max-w-7xl mx-auto">
          <h1 className="text-4xl font-bold mb-2">🏆 Competition Hub</h1>
          <p className="text-gray-400">
            Create events, manage scoring, and track results with official FINA standards.
          </p>
        </div>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-gray-800 bg-gray-900/50 sticky top-0 z-40">
        <div className="max-w-7xl mx-auto px-6">
          <div className="flex gap-8 overflow-x-auto">
            <button
              onClick={() => setActiveTab('create')}
              className={`py-4 px-2 border-b-2 font-medium whitespace-nowrap transition-colors ${
                activeTab === 'create'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Create Event
            </button>
            <button
              onClick={() => setActiveTab('active')}
              className={`py-4 px-2 border-b-2 font-medium whitespace-nowrap transition-colors ${
                activeTab === 'active'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Score Entry
            </button>
            <button
              onClick={() => setActiveTab('results')}
              className={`py-4 px-2 border-b-2 font-medium whitespace-nowrap transition-colors ${
                activeTab === 'results'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Results
            </button>
            <button
              onClick={() => setActiveTab('compliance')}
              className={`py-4 px-2 border-b-2 font-medium whitespace-nowrap transition-colors ${
                activeTab === 'compliance'
                  ? 'border-cyan-400 text-cyan-400'
                  : 'border-transparent text-gray-400 hover:text-gray-300'
              }`}
            >
              Compliance
            </button>
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="max-w-7xl mx-auto p-6">
        {error && (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 mb-6">
            <p className="text-red-400 font-semibold">⚠️ Error</p>
            <p className="text-red-300 text-sm mt-1">{error}</p>
          </div>
        )}

        {/* Create Event Tab */}
        {activeTab === 'create' && (
          <div className="space-y-6">
            <div className="bg-cyan-500/10 border border-cyan-500/30 rounded-lg p-6 mb-6">
              <h2 className="text-2xl font-bold mb-2">Create a New Event</h2>
              <p className="text-gray-400">
                Set up an official diving competition with FINA standards. Choose event type,
                height, and participants.
              </p>
            </div>
            <CompetitionEventSetup onEventCreated={handleEventCreated} />
          </div>
        )}

        {/* Score Entry Tab */}
        {activeTab === 'active' && (
          <div className="space-y-6">
            {/* Event Selector */}
            {events.length > 0 && (
              <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 mb-6">
                <h2 className="font-bold text-gray-300 mb-4">Select Event</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {events
                    .filter((e) => e.status === 'active' || e.status === 'setup')
                    .map((event) => (
                      <button
                        key={event.id}
                        onClick={() => {
                          setSelectedEventId(event.id)
                        }}
                        className={`p-4 rounded-lg border text-left transition-colors ${
                          selectedEventId === event.id
                            ? 'bg-cyan-500/20 border-cyan-500/50'
                            : 'bg-gray-800/50 border-gray-700 hover:bg-gray-800'
                        }`}
                      >
                        <p className="font-bold text-cyan-400">{event.event_type}</p>
                        <p className="text-sm text-gray-400 mt-1">
                          {event.height} • {event.dive_count} dives
                        </p>
                        <p className="text-xs text-gray-500 mt-2">
                          {new Date(event.created_at).toLocaleDateString()}
                        </p>
                      </button>
                    ))}
                </div>
              </div>
            )}

            {selectedEvent ? (
              <div className="space-y-6">
                <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-6">
                  <h2 className="text-2xl font-bold mb-2">📊 Score Entry</h2>
                  <p className="text-gray-400">
                    {selectedEvent.event_type} from {selectedEvent.height}
                  </p>
                </div>
                <CompetitionScoring eventId={selectedEvent.id} />
              </div>
            ) : (
              <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-12 text-center">
                <p className="text-gray-400">
                  {events.length === 0
                    ? 'No active events. Create one to get started.'
                    : 'Select an event to enter scores.'}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Results Tab */}
        {activeTab === 'results' && (
          <div className="space-y-6">
            {/* Event Selector */}
            {events.length > 0 && (
              <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-6 mb-6">
                <h2 className="font-bold text-gray-300 mb-4">Select Event</h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
                  {events.map((event) => (
                    <button
                      key={event.id}
                      onClick={() => {
                        setSelectedEventId(event.id)
                      }}
                      className={`p-4 rounded-lg border text-left transition-colors ${
                        selectedEventId === event.id
                          ? 'bg-cyan-500/20 border-cyan-500/50'
                          : 'bg-gray-800/50 border-gray-700 hover:bg-gray-800'
                      }`}
                    >
                      <p className="font-bold text-cyan-400">{event.event_type}</p>
                      <p className="text-sm text-gray-400 mt-1">
                        {event.height} • {event.dive_count} dives
                      </p>
                      <p className={`text-xs font-semibold mt-2 ${
                        event.status === 'finished' ? 'text-green-400' :
                        event.status === 'active' ? 'text-yellow-400' :
                        'text-gray-500'
                      }`}>
                        {event.status === 'finished' ? '✓ Finished' :
                         event.status === 'active' ? '● Active' :
                         '○ Setup'}
                      </p>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {selectedEvent ? (
              <div className="space-y-6">
                <div className="bg-purple-500/10 border border-purple-500/30 rounded-lg p-6">
                  <h2 className="text-2xl font-bold mb-2">🥇 Results</h2>
                  <p className="text-gray-400">
                    {selectedEvent.event_type} from {selectedEvent.height}
                  </p>
                </div>
                <CompetitionResults eventId={selectedEvent.id} />
              </div>
            ) : (
              <div className="bg-gray-800/50 border border-gray-700 rounded-lg p-12 text-center">
                <p className="text-gray-400">
                  {events.length === 0
                    ? 'No events available.'
                    : 'Select an event to view results.'}
                </p>
              </div>
            )}
          </div>
        )}

        {/* Compliance Tab */}
        {activeTab === 'compliance' && (
          <div className="space-y-6">
            <div className="bg-blue-500/10 border border-blue-500/30 rounded-lg p-6 mb-6">
              <h2 className="text-2xl font-bold mb-2">✓ FINA Compliance</h2>
              <p className="text-gray-400">
                Monitor data quality and FINA standards compliance across all dives.
              </p>
            </div>
            <ComplianceDashboard />
          </div>
        )}
      </div>
    </div>
  )
}

export default CompetitionHub
