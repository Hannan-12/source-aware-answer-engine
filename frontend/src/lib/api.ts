import type { SearchResponse } from "./types";

// Base URL of the FastAPI backend. Prefer NEXT_PUBLIC_API_BASE_URL while
// retaining NEXT_PUBLIC_API_URL as a compatibility alias for older setups.
const API_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ??
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

export class ApiError extends Error {}

// Calls the backend /search endpoint. Throws ApiError with a human-readable
// message on any failure so the UI can render it in the interface's voice.
export async function search(
  query: string,
  numResults = 6,
): Promise<SearchResponse> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}/search`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, num_results: numResults }),
    });
  } catch {
    throw new ApiError(
      "The answer service didn't respond — it may be offline.",
    );
  }

  if (res.status === 404) {
    // Backend signals "no usable results" — caller treats this as the empty state.
    throw new ApiError("__EMPTY__");
  }
  if (!res.ok) {
    let detail = `The service returned an error (${res.status}).`;
    try {
      const body = await res.json();
      if (body?.detail) detail = String(body.detail);
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(detail);
  }

  return (await res.json()) as SearchResponse;
}
