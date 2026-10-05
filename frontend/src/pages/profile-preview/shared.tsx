export interface MockUser {
  display_name: string;
  email: string;
  role: string;
  memberSince: string;
  totalDives: number;
  totalSessions: number;
  level: string;
}

export const mockUser: MockUser = {
  display_name: "Alex Moreau",
  email: "alex.moreau@example.com",
  role: "Member",
  memberSince: "Mar 2023",
  totalDives: 148,
  totalSessions: 32,
  level: "National",
};

export function initials(name: string) {
  return name
    .split(" ")
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      onClick={onChange}
      className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full border transition-colors ${
        checked ? "border-app-accent bg-app-accent" : "border-app bg-app-panel-elevated"
      }`}
    >
      <span
        className={`inline-block h-4 w-4 rounded-full bg-white transition-transform ${
          checked ? "translate-x-5" : "translate-x-1"
        }`}
      />
    </button>
  );
}

export const inputCls =
  "w-full border border-app bg-app-panel-elevated px-3 py-2.5 text-sm text-app-text focus:outline-none focus:ring-1 focus:ring-app-accent";

export const labelCls =
  "mb-1 block text-xs font-medium uppercase tracking-wide text-app-muted";
