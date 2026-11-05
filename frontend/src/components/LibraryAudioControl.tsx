import { Volume2, VolumeX } from 'lucide-react'
import { useTranslation } from 'react-i18next'
import { setLibraryAudioMuted, useLibraryAudioMuted } from '../utils/libraryAudioPreference'

export default function LibraryAudioControl() {
  const { t } = useTranslation()
  const muted = useLibraryAudioMuted()
  return <button type="button" className="library-audio-toggle inline-flex items-center justify-center border border-app text-app-text"
    aria-label={t(muted ? 'libraryUX.unmuteVideos' : 'libraryUX.muteVideos')}
    title={t(muted ? 'libraryUX.unmuteVideos' : 'libraryUX.muteVideos')}
    aria-pressed={muted} onClick={() => setLibraryAudioMuted(!muted)}>
    {muted ? <VolumeX size={16} aria-hidden="true" /> : <Volume2 size={16} aria-hidden="true" />}
    <span>{t(muted ? 'libraryUX.soundMuted' : 'libraryUX.soundOn')}</span>
  </button>
}
