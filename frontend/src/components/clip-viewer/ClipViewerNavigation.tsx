import { ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

export const PLAYBACK_RATES = [0.25, 0.5, 0.75, 1, 1.25, 1.5, 2] as const;

export default function ClipViewerNavigation({
  index,
  total,
  onPrevious,
  onNext,
  playbackRate,
  onPlaybackRateChange,
}: {
  index: number;
  total: number;
  onPrevious: () => void;
  onNext: () => void;
  playbackRate: number;
  onPlaybackRateChange: (rate: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex items-center justify-between gap-2">
      <button
        type="button"
        onClick={onPrevious}
        disabled={index <= 0}
        className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-4 text-sm text-app-text disabled:opacity-35"
      >
        <ChevronLeft className="h-4 w-4" />
        {t("clipNav.previous")}
        <kbd className="hidden text-[10px] text-app-muted lg:inline" aria-hidden="true">Shift+←</kbd>
      </button>
      <div className="flex min-w-0 items-center gap-2 sm:gap-3">
        <p className="text-sm text-app-muted" aria-live="polite">
          <span className="font-semibold text-app-text">{index + 1}</span>
          {" / "}
          {total}
        </p>
        <label className="flex items-center gap-1 text-xs text-app-muted">
          <span className="hidden sm:inline">{t("clipNav.speed")}</span>
          <select
            aria-label={t("clipNav.playbackSpeed")}
            value={playbackRate}
            onChange={(event) => onPlaybackRateChange(Number(event.target.value))}
            className="app-input w-20 py-1 text-sm"
          >
            {PLAYBACK_RATES.map((rate) => (
              <option key={rate} value={rate}>
                {rate}×
              </option>
            ))}
          </select>
        </label>
      </div>
      <button
        type="button"
        onClick={onNext}
        disabled={index >= total - 1}
        className="touch-target inline-flex items-center gap-2 border border-app bg-app-panel px-4 text-sm text-app-text disabled:opacity-35"
      >
        <kbd className="hidden text-[10px] text-app-muted lg:inline" aria-hidden="true">Shift+→</kbd>
        {t("clipNav.next")}
        <ChevronRight className="h-4 w-4" />
      </button>
    </div>
  );
}
