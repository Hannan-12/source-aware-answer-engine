"use client";

import { useEffect, useState } from "react";

// The case log: the pipeline's real steps, written out in real time like a
// clerk building the file — not a generic spinner. Respects reduced-motion by
// showing all lines at once with no cursor.
const STEPS = [
  "Searching sources",
  "Reviewing exhibits",
  "Preparing verdict",
];

export default function LoadingReadout({ query }: { query: string }) {
  const [reduced] = useState(
    () =>
      typeof window !== "undefined" &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const [step, setStep] = useState(() => (reduced ? STEPS.length - 1 : 0));

  useEffect(() => {
    if (reduced) return;
    const timers = [
      setTimeout(() => setStep(1), 1200),
      setTimeout(() => setStep(2), 2700),
    ];
    return () => timers.forEach(clearTimeout);
  }, [reduced]);

  return (
    <div
      className="font-mono text-sm text-shell-ink"
      role="status"
      aria-live="polite"
      aria-label={`Opening case: ${query}`}
    >
      {STEPS.map((label, i) => {
        const visible = reduced || i <= step;
        const active = !reduced && i === step;
        if (!visible) return null;
        return (
          <div
            key={label}
            className="flex items-center gap-2 py-0.5"
            style={{ color: i < step ? "var(--shell-muted)" : undefined }}
          >
            <span aria-hidden className="text-shell-muted">
              &gt;
            </span>
            <span>
              {label}
              {i < step ? " — done" : "…"}
            </span>
            {active && <span className="cursor">▋</span>}
          </div>
        );
      })}
    </div>
  );
}
