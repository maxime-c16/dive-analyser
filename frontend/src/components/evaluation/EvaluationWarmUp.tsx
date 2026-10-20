import { useTranslation } from 'react-i18next'

/** Three card backs bouncing on the springboard while the jury warms up. */
export default function EvaluationWarmUp() {
  const { t } = useTranslation()
  return (
    <div className="eval-warmup" role="status">
      <span className="eval-warmup-cards" aria-hidden><i /><i /><i /></span>
      <span className="eval-warmup-board" aria-hidden />
      <p>{t('evaluations.warmUp')}</p>
    </div>
  )
}
