import type { Attempt } from "../../utils/attemptPresentation";
import { attemptDetailRows } from "../../utils/attemptPresentation";

export default function ClipDetails({
  attempt,
  open,
}: {
  attempt: Attempt;
  open: boolean;
}) {
  return (
    <div
      id="clip-viewer-details"
      hidden={!open}
      className={`${open ? "grid" : "hidden"} gap-x-8 gap-y-0 text-sm sm:grid-cols-2`}
    >
      {attemptDetailRows(attempt).map(([label, value]) => (
        <div key={label} className="border-b border-app py-2.5">
          <dt className="text-xs text-app-muted">{label}</dt>
          <dd className="mt-0.5 text-app-text">{value}</dd>
        </div>
      ))}
    </div>
  );
}
