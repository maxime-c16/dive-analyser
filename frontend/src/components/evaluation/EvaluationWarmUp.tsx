import { useTranslation } from 'react-i18next'

/** Neutral loading state shared by evaluation journeys. */
export default function EvaluationWarmUp() {
  const { t } = useTranslation()
  return (
    <div className="eval-warmup" role="status">
      <p>{t('evaluations.warmUp')}</p>
    </div>
  )
}
