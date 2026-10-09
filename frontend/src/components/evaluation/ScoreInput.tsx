import { useTranslation } from 'react-i18next'
import { ScoreCard } from './ScoreCards'

/** No default vote: an integer selects the score, then ½ toggles its fraction. */
export default function ScoreInput({ score, disabled, onScore }: {
  score: number | null; disabled: boolean; onScore: (value: number) => void
}) {
  const { t } = useTranslation()
  const whole = score === null ? null : Math.floor(score / 2)
  const half = score !== null && score % 2 === 1
  return <div className="eval-score-input">
    <div className="eval-score-card">
      <ScoreCard scoreHalfSteps={score} ariaLabel={score === null ? t('evaluations.chooseScore') : t('evaluations.ariaScoreOf', { score: (score / 2).toFixed(1) })} />
      <span>{t('evaluations.you')}</span>
    </div>
    <div className="eval-score-controls">
      <div className="eval-half-row">
        <button type="button" className="eval-half-toggle" aria-pressed={half} disabled={disabled || whole === null || whole === 10}
          onClick={() => onScore(score! + (half ? -1 : 1))}>+ ½</button>
        <span className="eval-score-readout" aria-live="polite">{score === null ? t('evaluations.chooseScore') : `${(score / 2).toFixed(1)} / 10`}</span>
      </div>
      <div className="eval-keypad" role="group" aria-label={t('evaluations.scoreAria')}>
        {Array.from({ length: 11 }, (_, value) => <button key={value} type="button" disabled={disabled}
          aria-pressed={whole === value} aria-label={t('evaluations.ariaScoreOf', { score: value })}
          onClick={() => onScore(value * 2 + (value < 10 && half ? 1 : 0))}>{value}</button>)}
      </div>
    </div>
  </div>
}
