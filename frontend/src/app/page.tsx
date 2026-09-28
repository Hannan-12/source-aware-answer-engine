"use client";

import { useCallback, useMemo, useState } from "react";
import SearchBar from "@/components/SearchBar";
import Answer from "@/components/Answer";
import VerdictStamp from "@/components/VerdictStamp";
import SourceList from "@/components/SourceList";
import LoadingReadout from "@/components/LoadingReadout";
import { EmptyState, ErrorState } from "@/components/StateScreen";
import { search, ApiError } from "@/lib/api";
import { sanitizeQuery } from "@/lib/sanitizeQuery";
import type { SearchState } from "@/lib/types";

// A stable-ish case number derived from a counter, for the dossier ticker.
function caseNumber(seq: number): string {
  return `№${String(400 + seq).padStart(5, "0")}`;
}

export default function Home() {
  const [state, setState] = useState<SearchState>({ status: "idle" });
  const [history, setHistory] = useState<string[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [seq, setSeq] = useState(0);
  // Shared citation focus — the signature interaction lives here.
  const [activeCite, setActiveCite] = useState<number | null>(null);
  const [pulseCite, setPulseCite] = useState<number | null>(null);
  const [showWork, setShowWork] = useState(false);

  const runSearch = useCallback(async (rawQuery: string) => {
    const query = sanitizeQuery(rawQuery);
    if (!query) return;
    setActiveCite(null);
    setInputValue(query);
    setSeq((s) => s + 1);
    setState({ status: "loading", query });
    setHistory((h) => [query, ...h.filter((q) => q !== query)].slice(0, 8));
    try {
      const result = await search(query);
      setState({ status: "done", query, result });
    } catch (err) {
      if (err instanceof ApiError && err.message === "__EMPTY__") {
        setState({ status: "empty", query });
      } else {
        const message =
          err instanceof ApiError
            ? err.message
            : "Something went wrong on the way to a verdict.";
        setState({ status: "error", query, message });
      }
    }
  }, []);

  const onCiteClick = useCallback((n: number) => {
    setActiveCite(n);
    const el = document.getElementById(`exhibit-${n}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
      setPulseCite(n);
      window.setTimeout(() => setPulseCite(null), 750);
    }
  }, []);

  const busy = state.status === "loading";
  const showResults = state.status === "done";
  const stamp = useMemo(() => new Date().toISOString().slice(0, 16).replace("T", " "), []);

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col px-5 sm:px-8">
      {/* Roughening filter for the inked-stamp edge. */}
      <svg width="0" height="0" className="absolute" aria-hidden>
        <filter id="stamp-rough">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.9"
            numOctaves="2"
            result="noise"
          />
          <feDisplacementMap in="SourceGraphic" in2="noise" scale="1.4" />
        </filter>
      </svg>

      {/* Case header + question */}
      <header className="sticky top-0 z-10 -mx-5 border-b border-line bg-shell/95 px-5 py-4 backdrop-blur sm:-mx-8 sm:px-8">
        <div className="mb-2 flex items-center justify-between font-mono text-[0.7rem] uppercase tracking-[0.25em] text-shell-muted">
          <span>
            Case File · {seq > 0 ? caseNumber(seq) : "new"}
          </span>
          {seq > 0 && <span>{stamp}</span>}
        </div>
        <SearchBar
          value={inputValue}
          onChange={setInputValue}
          onSearch={runSearch}
          busy={busy}
        />
      </header>

      {/* Body */}
      <section className="flex-1 py-10">
        {state.status === "idle" && (
          <div className="max-w-prose pt-8">
            <h1 className="font-display text-3xl font-bold leading-tight text-shell-ink sm:text-4xl">
              Every answer is a case. Every claim, an exhibit. Every verdict,
              on the record.
            </h1>
            <p className="mt-4 font-body text-lg text-shell-muted">
              Ask a question and get a written answer with its evidence attached —
              and an honest verdict on whether the sources actually agree. Hover a{" "}
              <span className="cite-ref" data-active>
                [A]
              </span>{" "}
              to see the exhibit behind it.
            </p>
          </div>
        )}

        {state.status === "loading" && (
          <div className="pt-8">
            <LoadingReadout query={state.query} />
          </div>
        )}

        {state.status === "empty" && (
          <div className="pt-6">
            <EmptyState query={state.query} />
          </div>
        )}
        {state.status === "error" && (
          <div className="pt-6">
            <ErrorState message={state.message} />
          </div>
        )}

        {showResults && (
          <div className="grid grid-cols-1 gap-10 md:grid-cols-[1fr_20rem]">
            <div>
              {/* Answer sheet (parchment) with the verdict stamp pressed on. */}
              <div className="relative rounded-md bg-parchment p-6 sm:p-8">
                <div className="mb-4 flex items-start justify-between gap-4">
                  <h2 className="font-mono text-xs uppercase tracking-[0.25em] text-ink-soft">
                    Answer
                  </h2>
                  {state.result.agreement && (
                    <div className="-mt-1 shrink-0">
                      <VerdictStamp
                        agreement={state.result.agreement}
                        note={state.result.agreement_note ?? ""}
                        animateKey={`${seq}-${state.result.agreement}`}
                      />
                    </div>
                  )}
                </div>
                <Answer
                  answer={state.result.answer}
                  activeCite={activeCite}
                  onCiteHover={setActiveCite}
                  onCiteClick={onCiteClick}
                />
              </div>
            </div>
            <aside className="md:sticky md:top-32 md:self-start">
              <SourceList
                sources={state.result.sources}
                activeCite={activeCite}
                pulseCite={pulseCite}
                onHover={setActiveCite}
                showWork={showWork}
                onToggleWork={() => setShowWork((v) => !v)}
              />
            </aside>
          </div>
        )}
      </section>

      {/* Prior cases (session history) */}
      {history.length > 1 && (
        <footer className="border-t border-line py-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <span className="font-mono text-xs uppercase tracking-[0.25em] text-shell-muted">
              Prior cases
            </span>
            {history.slice(1).map((q) => (
              <button
                key={q}
                onClick={() => runSearch(q)}
                disabled={busy}
                className="font-body text-sm text-shell-muted hover:text-shell-ink disabled:opacity-40"
              >
                {q}
              </button>
            ))}
          </div>
        </footer>
      )}
    </main>
  );
}
