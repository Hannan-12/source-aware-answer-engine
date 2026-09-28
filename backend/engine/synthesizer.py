"""Synthesis layer: turn search results into a cited answer using an LLM.

This module takes the {title, url, snippet} results from the retriever, builds
a numbered source block, and asks Groq's Llama model to answer using ONLY those
sources with inline [n] citations. It knows nothing about how the results were
fetched — it can be tested in isolation with hardcoded results.
"""

from __future__ import annotations

import os

from .errors import MissingAPIKeyError, SynthesisError

DEFAULT_MODEL = "llama-3.3-70b-versatile"
TIMEOUT_SECONDS = 30.0


def get_model_name() -> str:
    """Return the configured Groq model, defaulting to a supported value."""
    return os.getenv("GROQ_MODEL", DEFAULT_MODEL)

SYSTEM_PROMPT = (
    "You are a search assistant. Answer the user's question using ONLY the "
    "numbered sources below. Cite each claim with its source number in "
    "brackets, e.g. [1].\n\n"
    "Length: match the answer to the question. For simple factual questions "
    "(a capital, a date, a definition), answer in 1-2 sentences. Save longer, "
    "multi-source explanations for genuinely ambiguous, disputed, or complex "
    "questions.\n\n"
    "Do not add a closing summary sentence that restates all the citations. "
    "Cite at most two sources per claim — pick the most authoritative ones "
    "rather than stacking every source that mentions the fact.\n\n"
    "Prefer the most authoritative sources (encyclopedias, official sites, "
    "reference works) over forums, social media, or quiz sites when they "
    "cover the same fact.\n\n"
    "If the sources don't contain enough information, say so explicitly rather "
    "than guessing."
)


def synthesize(query: str, results: list[dict]) -> str:
    """Synthesize a cited answer to ``query`` from search ``results``.

    Args:
        query: The user's original question.
        results: A list of {title, url, snippet} dicts from the retriever.

    Returns:
        A plain-text answer with inline [n] citations.

    Raises:
        MissingAPIKeyError: if ``GROQ_API_KEY`` is not set.
        SynthesisError: if there are no results or the LLM call fails.
    """
    query = (query or "").strip()
    if not query:
        raise SynthesisError("Query is empty.")
    if not results:
        raise SynthesisError("No sources to synthesize from.")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "GROQ_API_KEY is not set. Add it to your .env file "
            "(see .env.example). Get a free key at https://console.groq.com"
        )

    # Import here so the module loads even if `groq` isn't installed yet,
    # and so a missing key raises our clean error before we need the SDK.
    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise SynthesisError(
            "The 'groq' package is not installed. Run: pip install groq"
        ) from exc

    context = build_context(results)
    user_message = f"Question: {query}\n\nSources:\n{context}"

    client = Groq(api_key=api_key, timeout=TIMEOUT_SECONDS)
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
        )
    except Exception as exc:  # groq raises a variety of error subclasses
        raise SynthesisError(f"LLM request failed: {exc}") from exc

    answer = (completion.choices[0].message.content or "").strip()
    if not answer:
        raise SynthesisError("LLM returned an empty answer.")
    return answer


# Prompt for the structured variant: same answering rules, plus an assessment
# of how well the sources agree with each other on the key facts.
STRUCTURED_PROMPT = (
    SYSTEM_PROMPT
    + "\n\nReturn a JSON object with exactly these keys:\n"
    '  "answer": the cited answer text (same rules as above),\n'
    '  "agreement": one of "agree", "mixed", "single", or "none" —\n'
    '     "agree" if the sources that address the question broadly corroborate '
    "each other,\n"
    '     "mixed" if sources meaningfully conflict or give differing figures,\n'
    '     "single" if exactly one source really addresses the question,\n'
    '     "none" if none of the sources actually address the question '
    "(the search returned results, but they are off-topic or irrelevant),\n"
    '  "agreement_note": a short phrase (max ~12 words) describing the '
    'agreement, e.g. "3 sources agree; 1 gives a higher figure", or for '
    '"none": "no sources address this question".\n'
    "Base the assessment only on the provided sources."
)


def synthesize_structured(query: str, results: list[dict]) -> dict:
    """Like ``synthesize`` but also assess how well the sources agree.

    Returns a dict: ``{"answer": str, "agreement": str, "agreement_note": str}``.
    Falls back gracefully to a plain answer with ``agreement="single"`` if the
    model doesn't return valid JSON.
    """
    query = (query or "").strip()
    if not query:
        raise SynthesisError("Query is empty.")
    if not results:
        raise SynthesisError("No sources to synthesize from.")

    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise MissingAPIKeyError(
            "GROQ_API_KEY is not set. Add it to your .env file "
            "(see .env.example). Get a free key at https://console.groq.com"
        )

    try:
        from groq import Groq
    except ImportError as exc:  # pragma: no cover - install-time guard
        raise SynthesisError(
            "The 'groq' package is not installed. Run: pip install groq"
        ) from exc

    context = build_context(results)
    user_message = f"Question: {query}\n\nSources:\n{context}"

    client = Groq(api_key=api_key, timeout=TIMEOUT_SECONDS)
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": STRUCTURED_PROMPT},
                {"role": "user", "content": user_message},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        raise SynthesisError(f"LLM request failed: {exc}") from exc

    raw = (completion.choices[0].message.content or "").strip()
    if not raw:
        raise SynthesisError("LLM returned an empty answer.")

    import json

    # Default agreement based on the actual source count, so a fallback never
    # claims "single source" when several sources were retrieved.
    default_agreement = "single" if len(results) == 1 else "agree"

    try:
        data = json.loads(raw)
        answer = str(data.get("answer", "")).strip()
        agreement = str(data.get("agreement", default_agreement)).strip().lower()
        note = str(data.get("agreement_note", "")).strip()
    except (json.JSONDecodeError, AttributeError):
        # Model didn't return clean JSON — degrade to a plain answer.
        return {
            "answer": raw,
            "agreement": default_agreement,
            "agreement_note": "",
        }

    if not answer:
        raise SynthesisError("LLM returned an empty answer.")
    if agreement not in ("agree", "mixed", "single", "none"):
        agreement = default_agreement
    # "single" only makes sense with one source; with several, treat a stray
    # "single" from the model as "agree" unless it meant "none".
    if agreement == "single" and len(results) > 1:
        agreement = "agree"
    return {"answer": answer, "agreement": agreement, "agreement_note": note}


def build_context(results: list[dict]) -> str:
    """Build the numbered source block fed to the LLM.

    Each line looks like: ``[1] Title — snippet (url)``. The numbering here is
    the same numbering the model is told to cite with, so the [n] in the answer
    lines up with the source list the CLI/API prints.
    """
    lines: list[str] = []
    for i, r in enumerate(results, start=1):
        title = (r.get("title") or "").strip() or "Untitled"
        snippet = (r.get("snippet") or "").strip()
        url = (r.get("url") or "").strip()
        lines.append(f"[{i}] {title} — {snippet} ({url})")
    return "\n".join(lines)


if __name__ == "__main__":
    # Manual smoke test (Step 3 of the build plan: test with HARDCODED results
    # before wiring to the live retriever). Run: python -m engine.synthesizer
    from dotenv import load_dotenv

    load_dotenv()

    sample_results = [
        {
            "title": "What is RAG? - IBM",
            "url": "https://www.ibm.com/topics/retrieval-augmented-generation",
            "snippet": (
                "Retrieval-augmented generation (RAG) connects an AI model with "
                "external knowledge bases so LLMs give more relevant answers."
            ),
        },
        {
            "title": "Retrieval-augmented generation - Wikipedia",
            "url": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
            "snippet": (
                "RAG lets large language models retrieve and incorporate new "
                "information from external data sources before responding."
            ),
        },
    ]

    print("--- Context sent to LLM ---")
    print(build_context(sample_results))
    print("\n--- Synthesized answer ---")
    print(synthesize("What is retrieval-augmented generation?", sample_results))
