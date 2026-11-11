/**
 * Typed API client. The session-aware fetch wrapper and generated route types
 * are added once the Stage 1 API contract exists.
 */
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/healthz`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return (await response.json()) as { status: string };
}
