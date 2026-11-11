/**
 * Typed API client.
 *
 * Talks to the FastAPI backend with the browser session cookie
 * (``credentials: include``) and the double-submit CSRF token that the API
 * requires on mutations. Errors follow RFC 7807 and are surfaced as
 * {@link ApiError} so callers can show ``detail`` and act on ``code``.
 */
import type {
  Template,
  TemplateRenderResult,
  TemplateStatus,
  TemplateSummary,
  TemplateTestSendResult,
} from "@email-platform/shared-schemas";

export * from "@email-platform/shared-schemas";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

const CSRF_COOKIE_NAME = process.env.NEXT_PUBLIC_CSRF_COOKIE_NAME ?? "csrf_token";
const CSRF_HEADER_NAME = process.env.NEXT_PUBLIC_CSRF_HEADER_NAME ?? "X-CSRF-Token";

export interface ProblemDetails {
  type?: string;
  title?: string;
  status?: number;
  detail?: string;
  instance?: string;
  [key: string]: unknown;
}

export class ApiError extends Error {
  readonly status: number;
  /** Stable problem code, e.g. ``validation_error`` or ``forbidden``. */
  readonly code: string;
  readonly body: ProblemDetails;

  constructor(body: ProblemDetails, status: number) {
    super(body.detail ?? body.title ?? `Request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.code = body.title ?? "error";
    this.body = body;
  }
}

function readCookie(name: string): string | null {
  if (typeof document === "undefined") {
    return null;
  }
  const prefix = `${name}=`;
  const match = document.cookie.split("; ").find((row) => row.startsWith(prefix));
  return match ? decodeURIComponent(match.slice(prefix.length)) : null;
}

function parseBody(text: string): ProblemDetails | null {
  if (!text) {
    return null;
  }
  try {
    return JSON.parse(text) as ProblemDetails;
  } catch {
    return { detail: text };
  }
}

interface RequestOptions {
  method?: string;
  body?: unknown;
  signal?: AbortSignal;
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (method !== "GET" && method !== "HEAD") {
    const token = readCookie(CSRF_COOKIE_NAME);
    if (token) {
      headers[CSRF_HEADER_NAME] = token;
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers,
    credentials: "include",
    cache: "no-store",
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
    signal: options.signal,
  });

  if (response.status === 204) {
    return undefined as T;
  }
  const text = await response.text();
  const payload = parseBody(text);
  if (!response.ok) {
    throw new ApiError(payload ?? {}, response.status);
  }
  return payload as T;
}

/* ------------------------------------------------------------------ ops */

export async function getHealth(): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE_URL}/healthz`, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Health check failed: ${response.status}`);
  }
  return (await response.json()) as { status: string };
}

/* -------------------------------------------------------------- templates */

export interface TemplateWriteInput {
  name: string;
  mjml_source: string;
  editor_json?: Record<string, unknown>;
  status?: TemplateStatus;
}

export interface TemplateRenderInput {
  values?: Record<string, string>;
}

export interface TemplateTestSendInput {
  recipient: string;
  subject: string;
  values?: Record<string, string>;
}

export function listTemplates(signal?: AbortSignal): Promise<TemplateSummary[]> {
  return apiFetch<TemplateSummary[]>("/api/v1/templates", { signal });
}

export function getTemplate(id: string, signal?: AbortSignal): Promise<Template> {
  return apiFetch<Template>(`/api/v1/templates/${id}`, { signal });
}

export function createTemplate(input: TemplateWriteInput): Promise<Template> {
  return apiFetch<Template>("/api/v1/templates", { method: "POST", body: input });
}

export function updateTemplate(
  id: string,
  input: Partial<TemplateWriteInput>,
): Promise<Template> {
  return apiFetch<Template>(`/api/v1/templates/${id}`, { method: "PATCH", body: input });
}

export function archiveTemplate(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/templates/${id}`, { method: "DELETE" });
}

export function renderTemplate(
  id: string,
  input: TemplateRenderInput = {},
): Promise<TemplateRenderResult> {
  return apiFetch<TemplateRenderResult>(`/api/v1/templates/${id}/render`, {
    method: "POST",
    body: input,
  });
}

export function testSendTemplate(
  id: string,
  input: TemplateTestSendInput,
): Promise<TemplateTestSendResult> {
  return apiFetch<TemplateTestSendResult>(`/api/v1/templates/${id}/test-send`, {
    method: "POST",
    body: input,
  });
}
