import type { Attempt } from "../../utils/attemptPresentation";
import {
  attemptDate,
  attemptScore,
  performanceClass,
  performanceLabel,
} from "../../utils/attemptPresentation";

export default function ClipMetadataSummary({ attempt }: { attempt: Attempt }) {
  const score = attemptScore(attempt);
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
      <p className="min-w-0 text-sm text-app-muted">
        <span className="font-medium text-app-text">{attempt.height}</span>
        {" · "}
        {attempt.platform_type}
        {" · "}
        {attemptDate(attempt)}
      </p>
      <div className="flex shrink-0 items-center gap-2">
        <span
          className={`inline-flex border px-2 py-1 text-xs font-medium ${performanceClass[attempt.performance] || performanceClass.M}`}
        >
          {performanceLabel[attempt.performance] || attempt.performance}
        </span>
        <span className="text-sm font-semibold text-app-text">
          {score.toFixed(1)} / 10
        </span>
      </div>
    </div>
  );
}
