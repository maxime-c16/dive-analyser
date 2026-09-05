import React, { useState } from 'react'
import { api } from '../services/api'
import { Brain, CheckCircle2, Frown, Heart, ShieldAlert, Smile, Sparkles, ThumbsUp, type LucideIcon } from 'lucide-react'

interface EmotionalStateProps {
  diveId: number
  diveCode: string
  onSubmitted?: () => void
}

const EMOTIONS_BEFORE: Array<{ value: string; label: string; icon: LucideIcon }> = [
  { value: 'confident', label: 'Confident', icon: ThumbsUp },
  { value: 'nervous', label: 'Nervous', icon: Frown },
  { value: 'excited', label: 'Excited', icon: Sparkles },
  { value: 'fearful', label: 'Fearful', icon: ShieldAlert },
  { value: 'anxious', label: 'Anxious', icon: Brain },
]

const EMOTIONS_AFTER: Array<{ value: string; label: string; icon: LucideIcon }> = [
  { value: 'satisfied', label: 'Satisfied', icon: Smile },
  { value: 'frustrated', label: 'Frustrated', icon: Frown },
  { value: 'proud', label: 'Proud', icon: Heart },
  { value: 'disappointed', label: 'Disappointed', icon: Frown },
  { value: 'relieved', label: 'Relieved', icon: CheckCircle2 },
]

function EmotionalStateCapture({ diveId, diveCode, onSubmitted }: EmotionalStateProps) {
  const [preEmotion, setPreEmotion] = useState<string | null>(null)
  const [postEmotion, setPostEmotion] = useState<string | null>(null)
  const [confidence, setConfidence] = useState(3)
  const [loading, setLoading] = useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async () => {
    if (!preEmotion || !postEmotion) {
      setError('Please select both pre- and post-dive emotions')
      return
    }

    try {
      setLoading(true)
      await api.post(`/api/v1/dives/${diveId}/emotional-state`, {
        pre_dive_emotion: preEmotion,
        post_dive_emotion: postEmotion,
        confidence_rating: confidence,
      })
      setSubmitted(true)
      setError(null)
      if (onSubmitted) {
        onSubmitted()
      }
      // Reset after 2 seconds
      setTimeout(() => {
        setSubmitted(false)
        setPreEmotion(null)
        setPostEmotion(null)
        setConfidence(3)
      }, 2000)
    } catch (err) {
      console.error('Error saving emotional state:', err)
      setError('Failed to save emotional state')
    } finally {
      setLoading(false)
    }
  }

  if (submitted) {
    return (
      <div className="bg-green-500/20 border border-green-500/50 rounded-lg p-4 text-center">
        <div className="flex items-center justify-center gap-2 font-bold text-green-400"><CheckCircle2 className="h-4 w-4" aria-hidden="true" />Emotions saved</div>
        <p className="text-green-300 text-sm mt-1">Thank you for tracking your emotions.</p>
      </div>
    )
  }

  return (
    <div className="bg-gray-800 rounded-lg p-6 border border-gray-700">
      <div className="mb-4">
        <h3 className="mb-2 flex items-center gap-2 text-lg font-bold text-purple-400"><Brain className="h-5 w-5" aria-hidden="true" />How did you feel about dive {diveCode}?</h3>
        <p className="text-gray-400 text-sm">Your emotions help us understand your confidence journey.</p>
      </div>

      {error && (
        <div className="bg-red-500/20 border border-red-500/50 rounded p-3 mb-4 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Pre-dive Emotions */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-cyan-400 mb-3">Before the dive:</label>
        <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
          {EMOTIONS_BEFORE.map((emotion) => {
            const Icon = emotion.icon
            return (
            <button
              key={emotion.value}
              onClick={() => setPreEmotion(emotion.value)}
              className={`p-3 rounded-lg border-2 transition-all text-center ${
                preEmotion === emotion.value
                  ? 'border-cyan-400 bg-cyan-500/20'
                  : 'border-gray-600 bg-gray-700 hover:border-gray-500'
              }`}
              disabled={loading}
            >
              <Icon className="mx-auto mb-1 h-5 w-5" aria-hidden="true" />
              <div className="text-xs font-medium">{emotion.label}</div>
            </button>
          )})}
        </div>
      </div>

      {/* Post-dive Emotions */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-green-400 mb-3">After the dive:</label>
        <div className="grid grid-cols-3 md:grid-cols-5 gap-2">
          {EMOTIONS_AFTER.map((emotion) => {
            const Icon = emotion.icon
            return (
            <button
              key={emotion.value}
              onClick={() => setPostEmotion(emotion.value)}
              className={`p-3 rounded-lg border-2 transition-all text-center ${
                postEmotion === emotion.value
                  ? 'border-green-400 bg-green-500/20'
                  : 'border-gray-600 bg-gray-700 hover:border-gray-500'
              }`}
              disabled={loading}
            >
              <Icon className="mx-auto mb-1 h-5 w-5" aria-hidden="true" />
              <div className="text-xs font-medium">{emotion.label}</div>
            </button>
          )})}
        </div>
      </div>

      {/* Confidence Rating */}
      <div className="mb-6">
        <label className="block text-sm font-medium text-yellow-400 mb-3">
          Confidence level: {confidence}/5
        </label>
        <input
          type="range"
          min="1"
          max="5"
          value={confidence}
          onChange={(e) => setConfidence(parseInt(e.target.value))}
          disabled={loading}
          className="w-full h-2 bg-gray-700 rounded-lg appearance-none cursor-pointer accent-yellow-400"
        />
        <div className="flex justify-between text-xs text-gray-500 mt-2">
          <span>Very Unconfident</span>
          <span>Very Confident</span>
        </div>
      </div>

      {/* Submit Button */}
      <button
        onClick={handleSubmit}
        disabled={loading || !preEmotion || !postEmotion}
        className={`w-full py-2 rounded-lg font-medium transition-all ${
          loading || !preEmotion || !postEmotion
            ? 'bg-gray-600 text-gray-400 cursor-not-allowed'
            : 'bg-purple-600 hover:bg-purple-700 text-white'
        }`}
      >
        {loading ? 'Saving...' : 'Save Emotional State'}
      </button>
    </div>
  )
}

export default EmotionalStateCapture
