/**
 * Typed API client.
 *
 * Talks to the FastAPI backend with the browser session cookie
 * (``credentials: include``) and the double-submit CSRF token that the API
 * requires on mutations. Errors follow RFC 7807 and are surfaced as
 * {@link ApiError} so callers can show ``detail`` and act on ``code``.
 */
import type {
  CampaignAnalytics,
  CampaignCreateInput,
  CampaignOut,
  CampaignPage,
  CampaignUpdateInput,
  CapacityRefreshResult,
  ContactCreateInput,
  ContactOut,
  ContactPage,
  ContactUpdateInput,
  CredentialOut,
  ImportCreated,
  ImportMapping,
  ImportOut,
  ImportPreview,
  LaunchResult,
  LaunchValidationResult,
  MeOut,
  MergePolicy,
  ProviderAccountCreateInput,
  ProviderAccountDetail,
  ProviderAccountOut,
  ProviderAccountPage,
  ProviderAccountUpdateInput,
  RecipientPage,
  RoutingStatus,
  ScheduleRequestInput,
  ScheduleResult,
  SegmentDefinition,
  SegmentEstimate,
  SegmentOut,
  SuppressionCreateInput,
  SuppressionOut,
  TagOut,
  Template,
  TemplateRenderResult,
  TemplateStatus,
  TemplateSummary,
  TemplateTestSendResult,
  VerifyResult,
  WorkspaceOut,
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
  /** Query parameters; ``undefined`` and ``null`` values are omitted. */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** Extra request headers, e.g. ``Idempotency-Key``. */
  headers?: Record<string, string>;
}

function buildQuery(query: RequestOptions["query"]): string {
  if (!query) {
    return "";
  }
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") {
      continue;
    }
    params.set(key, String(value));
  }
  const serialized = params.toString();
  return serialized ? `?${serialized}` : "";
}

export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const method = (options.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = { Accept: "application/json", ...options.headers };
  if (options.body !== undefined) {
    headers["Content-Type"] = "application/json";
  }
  if (method !== "GET" && method !== "HEAD") {
    const token = readCookie(CSRF_COOKIE_NAME);
    if (token) {
      headers[CSRF_HEADER_NAME] = token;
    }
  }

  const response = await fetch(`${API_BASE_URL}${path}${buildQuery(options.query)}`, {
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

/* ----------------------------------------------------------------- identity */

/**
 * OAuth entry point. It is a top-level navigation, not a fetch: the callback
 * sets the session cookie and redirects back to the app.
 */
export const GOOGLE_SIGN_IN_URL = `${API_BASE_URL}/api/v1/auth/google/start`;

export function getMe(signal?: AbortSignal): Promise<MeOut> {
  return apiFetch<MeOut>("/api/v1/me", { signal });
}

export function getWorkspace(signal?: AbortSignal): Promise<WorkspaceOut> {
  return apiFetch<WorkspaceOut>("/api/v1/workspace", { signal });
}

export function logout(): Promise<void> {
  return apiFetch<void>("/api/v1/auth/logout", { method: "POST" });
}

/* ----------------------------------------------------------------- audience */

export interface ContactListQuery {
  cursor?: string | null;
  limit?: number;
  status?: string;
  consent_status?: string;
  tag_id?: string;
  search?: string;
}

export function listContacts(
  query: ContactListQuery = {},
  signal?: AbortSignal,
): Promise<ContactPage> {
  return apiFetch<ContactPage>("/api/v1/contacts", { query, signal });
}

export function getContact(id: string, signal?: AbortSignal): Promise<ContactOut> {
  return apiFetch<ContactOut>(`/api/v1/contacts/${id}`, { signal });
}

export function createContact(input: ContactCreateInput): Promise<ContactOut> {
  return apiFetch<ContactOut>("/api/v1/contacts", { method: "POST", body: input });
}

export function updateContact(id: string, input: ContactUpdateInput): Promise<ContactOut> {
  return apiFetch<ContactOut>(`/api/v1/contacts/${id}`, { method: "PATCH", body: input });
}

export function deleteContact(id: string): Promise<void> {
  return apiFetch<void>(`/api/v1/contacts/${id}`, { method: "DELETE" });
}

export function suppressContact(
  id: string,
  input: SuppressionCreateInput,
): Promise<SuppressionOut> {
  return apiFetch<SuppressionOut>(`/api/v1/contacts/${id}/suppress`, {
    method: "POST",
    body: input,
  });
}

export function listTags(signal?: AbortSignal): Promise<TagOut[]> {
  return apiFetch<TagOut[]>("/api/v1/tags", { signal });
}

export function createTag(name: string): Promise<TagOut> {
  return apiFetch<TagOut>("/api/v1/tags", { method: "POST", body: { name } });
}

export function attachTag(contactId: string, tagId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/contacts/${contactId}/tags/${tagId}`, { method: "PUT" });
}

export function detachTag(contactId: string, tagId: string): Promise<void> {
  return apiFetch<void>(`/api/v1/contacts/${contactId}/tags/${tagId}`, { method: "DELETE" });
}

/** Download the CSV export as a blob (the session cookie is required). */
export async function exportContactsCsv(): Promise<Blob> {
  const response = await fetch(`${API_BASE_URL}/api/v1/contacts/export`, {
    credentials: "include",
    cache: "no-store",
  });
  if (!response.ok) {
    const payload = parseBody(await response.text());
    throw new ApiError(payload ?? {}, response.status);
  }
  return response.blob();
}

/* ----------------------------------------------------------------- segments */

export function listSegments(signal?: AbortSignal): Promise<SegmentOut[]> {
  return apiFetch<SegmentOut[]>("/api/v1/segments", { signal });
}

export function getSegment(id: string, signal?: AbortSignal): Promise<SegmentOut> {
  return apiFetch<SegmentOut>(`/api/v1/segments/${id}`, { signal });
}

export function createSegment(name: string, definition: SegmentDefinition): Promise<SegmentOut> {
  return apiFetch<SegmentOut>("/api/v1/segments", {
    method: "POST",
    body: { name, definition },
  });
}

export function updateSegment(
  id: string,
  name: string,
  definition: SegmentDefinition,
): Promise<SegmentOut> {
  return apiFetch<SegmentOut>(`/api/v1/segments/${id}`, {
    method: "PATCH",
    body: { name, definition },
  });
}

export function estimateSegment(id: string, signal?: AbortSignal): Promise<SegmentEstimate> {
  return apiFetch<SegmentEstimate>(`/api/v1/segments/${id}/estimate`, { signal });
}

/* ------------------------------------------------------------------ imports */

export function createImport(
  mapping: ImportMapping,
  idempotencyKey?: string,
): Promise<ImportCreated> {
  return apiFetch<ImportCreated>("/api/v1/imports", {
    method: "POST",
    body: { mapping },
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function getImport(id: string, signal?: AbortSignal): Promise<ImportOut> {
  return apiFetch<ImportOut>(`/api/v1/imports/${id}`, { signal });
}

export function previewImport(id: string): Promise<ImportPreview> {
  return apiFetch<ImportPreview>(`/api/v1/imports/${id}/preview`, { method: "POST" });
}

export function commitImport(id: string, mergePolicy: MergePolicy): Promise<ImportOut> {
  return apiFetch<ImportOut>(`/api/v1/imports/${id}/commit`, {
    method: "POST",
    body: { merge_policy: mergePolicy },
  });
}

/**
 * Upload the staged CSV to the short-lived presigned URL.
 *
 * The URL is pre-signed, so no session or CSRF header is sent: adding them
 * would invalidate the signature.
 */
export async function uploadImportFile(uploadUrl: string, file: File): Promise<void> {
  const response = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": "text/csv" },
    body: file,
  });
  if (!response.ok) {
    throw new Error(`Upload failed with status ${response.status}`);
  }
}

/* ---------------------------------------------------------------- campaigns */

export interface CampaignListQuery {
  cursor?: string | null;
  limit?: number;
  status?: string;
}

export function listCampaigns(
  query: CampaignListQuery = {},
  signal?: AbortSignal,
): Promise<CampaignPage> {
  return apiFetch<CampaignPage>("/api/v1/campaigns", { query, signal });
}

export function getCampaign(id: string, signal?: AbortSignal): Promise<CampaignOut> {
  return apiFetch<CampaignOut>(`/api/v1/campaigns/${id}`, { signal });
}

export function createCampaign(
  input: CampaignCreateInput,
  idempotencyKey?: string,
): Promise<CampaignOut> {
  return apiFetch<CampaignOut>("/api/v1/campaigns", {
    method: "POST",
    body: input,
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function updateCampaign(id: string, input: CampaignUpdateInput): Promise<CampaignOut> {
  return apiFetch<CampaignOut>(`/api/v1/campaigns/${id}`, { method: "PATCH", body: input });
}

export function validateCampaign(id: string): Promise<LaunchValidationResult> {
  return apiFetch<LaunchValidationResult>(`/api/v1/campaigns/${id}/validate`, { method: "POST" });
}

export function scheduleCampaign(
  id: string,
  input: ScheduleRequestInput,
): Promise<ScheduleResult> {
  return apiFetch<ScheduleResult>(`/api/v1/campaigns/${id}/schedule`, {
    method: "POST",
    body: input,
  });
}

export function launchCampaign(id: string, idempotencyKey?: string): Promise<LaunchResult> {
  return apiFetch<LaunchResult>(`/api/v1/campaigns/${id}/launch`, {
    method: "POST",
    headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined,
  });
}

export function pauseCampaign(id: string): Promise<CampaignOut> {
  return apiFetch<CampaignOut>(`/api/v1/campaigns/${id}/pause`, { method: "POST" });
}

export function resumeCampaign(id: string): Promise<CampaignOut> {
  return apiFetch<CampaignOut>(`/api/v1/campaigns/${id}/resume`, { method: "POST" });
}

export function cancelCampaign(id: string): Promise<CampaignOut> {
  return apiFetch<CampaignOut>(`/api/v1/campaigns/${id}/cancel`, { method: "POST" });
}

export interface RecipientListQuery {
  cursor?: string | null;
  limit?: number;
  status?: string;
}

export function listRecipients(
  campaignId: string,
  query: RecipientListQuery = {},
  signal?: AbortSignal,
): Promise<RecipientPage> {
  return apiFetch<RecipientPage>(`/api/v1/campaigns/${campaignId}/recipients`, { query, signal });
}

/**
 * Ledger state plus provider-reported totals.
 *
 * ``accepted`` (provider acceptance) and ``delivered`` (provider-reported
 * delivery) are separate numbers, and unresolved recipients stay ``unknown``.
 */
export function getCampaignAnalytics(
  campaignId: string,
  signal?: AbortSignal,
): Promise<CampaignAnalytics> {
  return apiFetch<CampaignAnalytics>(`/api/v1/campaigns/${campaignId}/analytics`, { signal });
}

/* ---------------------------------------------------------------- providers */

export interface ProviderAccountListQuery {
  cursor?: string | null;
  limit?: number;
  status?: string;
}

export function listProviderAccounts(
  query: ProviderAccountListQuery = {},
  signal?: AbortSignal,
): Promise<ProviderAccountPage> {
  return apiFetch<ProviderAccountPage>("/api/v1/provider-accounts", { query, signal });
}

export function getProviderAccount(
  id: string,
  signal?: AbortSignal,
): Promise<ProviderAccountDetail> {
  return apiFetch<ProviderAccountDetail>(`/api/v1/provider-accounts/${id}`, { signal });
}

export function createProviderAccount(
  input: ProviderAccountCreateInput,
): Promise<ProviderAccountDetail> {
  return apiFetch<ProviderAccountDetail>("/api/v1/provider-accounts", {
    method: "POST",
    body: input,
  });
}

export function updateProviderAccount(
  id: string,
  input: ProviderAccountUpdateInput,
): Promise<ProviderAccountOut> {
  return apiFetch<ProviderAccountOut>(`/api/v1/provider-accounts/${id}`, {
    method: "PATCH",
    body: input,
  });
}

export function addProviderCredential(
  accountId: string,
  secret: string,
  label: string,
): Promise<CredentialOut> {
  return apiFetch<CredentialOut>(`/api/v1/provider-accounts/${accountId}/credentials`, {
    method: "POST",
    body: { secret, label },
  });
}

export function revokeProviderCredential(
  accountId: string,
  credentialId: string,
): Promise<CredentialOut> {
  return apiFetch<CredentialOut>(
    `/api/v1/provider-accounts/${accountId}/credentials/${credentialId}/revoke`,
    { method: "POST" },
  );
}

export function verifyProviderAccount(accountId: string): Promise<VerifyResult> {
  return apiFetch<VerifyResult>(`/api/v1/provider-accounts/${accountId}/verify`, {
    method: "POST",
  });
}

export function refreshProviderAccountCapacity(
  accountId: string,
): Promise<CapacityRefreshResult> {
  return apiFetch<CapacityRefreshResult>(
    `/api/v1/provider-accounts/${accountId}/refresh-quota`,
    { method: "POST" },
  );
}

export function getRoutingStatus(signal?: AbortSignal): Promise<RoutingStatus> {
  return apiFetch<RoutingStatus>("/api/v1/provider-accounts/routing-status", { signal });
}

export function setRoutingPause(paused: boolean, reason?: string): Promise<RoutingStatus> {
  return apiFetch<RoutingStatus>("/api/v1/provider-accounts/routing-pause", {
    method: "POST",
    body: { paused, reason: reason || null },
  });
}
