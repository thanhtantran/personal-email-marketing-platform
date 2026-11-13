/**
 * Shared, stable schemas/types used by both web and api-client. Populated as
 * API contracts stabilize in later stages.
 */
export type TenantId = string;

export type ContactStatus = "active" | "unsubscribed" | "suppressed" | "invalid";

export type CampaignStatus =
  | "draft"
  | "scheduled"
  | "preparing"
  | "sending"
  | "paused"
  | "completed"
  | "cancelled"
  | "failed";

/* ------------------------------------------------------------------ templates */

export type TemplateStatus = "draft" | "published" | "archived";

export interface TemplateSummary {
  id: string;
  name: string;
  version: number;
  status: TemplateStatus;
  created_at: string;
  updated_at: string;
}

export interface Template extends TemplateSummary {
  /** GrapesJS project data: the saved editor state. */
  editor_json: Record<string, unknown>;
  /** Authoritative source; the server renders this and never the editor state. */
  mjml_source: string;
  /** Derived, sanitized output. */
  html: string;
  text_body: string;
}

export interface TemplateRenderResult {
  template_id: string;
  version: number;
  html: string;
  text: string;
  /** Required variables that resolved to nothing. */
  missing: string[];
  /** Variables that fell back to their declared default. */
  used_fallback: string[];
}

export interface TemplateTestSendResult {
  template_id: string;
  version: number;
  provider: string;
  recipient: string;
  subject: string;
  digest: string;
  /** Always false: a test send never enqueues a production campaign. */
  enqueued: boolean;
  html: string;
  text: string;
  missing: string[];
  used_fallback: string[];
}

/**
 * MJML components the editor may emit. Mirrors the server allowlist in
 * `app/domain/content/editor.py`; anything outside this set is rejected by the
 * API. `mj-raw`, `mj-html` and `mj-script` are deliberately excluded so an
 * author cannot smuggle raw markup past MJML structure.
 */
export const SUPPORTED_MJML_COMPONENTS = [
  "mjml",
  "mj-body",
  "mj-section",
  "mj-column",
  "mj-wrapper",
  "mj-group",
  "mj-hero",
  "mj-text",
  "mj-image",
  "mj-button",
  "mj-divider",
  "mj-spacer",
  "mj-social",
  "mj-social-element",
  "mj-navbar",
  "mj-navbar-link",
  "mj-table",
  "mj-style",
] as const;

export type SupportedMjmlComponent = (typeof SUPPORTED_MJML_COMPONENTS)[number];

/**
 * Personalization variables the server will substitute. Mirrors
 * `BUILTIN_VARIABLES` in `app/domain/content/personalization.py`; contact
 * attributes are addressable as `attribute.<key>`.
 */
export const PERSONALIZATION_VARIABLES = [
  "email",
  "first_name",
  "last_name",
  "full_name",
  "company",
] as const;

export type PersonalizationVariable = (typeof PERSONALIZATION_VARIABLES)[number];

/* ----------------------------------------------------------------- identity */

export interface UserOut {
  id: string;
  email: string;
  display_name: string | null;
  status: string;
}

export interface WorkspaceOut {
  id: string;
  slug: string;
  name: string;
  status: string;
}

export interface MeOut {
  user: UserOut;
  workspace: WorkspaceOut;
  role: string;
  csrf_token_present: boolean;
}

/* ----------------------------------------------------------------- audience */

export const CONTACT_STATUSES = [
  "active",
  "unsubscribed",
  "suppressed",
  "invalid",
] as const satisfies readonly ContactStatus[];

export type ConsentStatus = "granted" | "denied" | "unknown" | "pending";

export const CONSENT_STATUSES = ["granted", "denied", "unknown", "pending"] as const;

export type SuppressionReason =
  | "unsubscribe"
  | "complaint"
  | "hard_bounce"
  | "manual"
  | "import";

export const SUPPRESSION_REASONS = [
  "unsubscribe",
  "complaint",
  "hard_bounce",
  "manual",
  "import",
] as const;

/**
 * Suppression reasons that mirror into an unrecoverable contact status (mirrors
 * `_STATUS_BY_REASON` in `app/domain/audience/consent.py`).
 */
export const SUPPRESSION_MIRRORED_STATUS: Partial<Record<SuppressionReason, ContactStatus>> = {
  unsubscribe: "unsubscribed",
  complaint: "suppressed",
  hard_bounce: "suppressed",
};

export interface TagOut {
  id: string;
  name: string;
}

export interface ContactOut {
  id: string;
  normalized_email: string;
  email_display: string;
  status: string;
  consent_status: string;
  consent_at: string | null;
  consent_source: string | null;
  consent_evidence_ref: string | null;
  attributes: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  tags: TagOut[];
}

export interface ContactPage {
  items: ContactOut[];
  next_cursor: string | null;
  total: number;
}

export interface ContactCreateInput {
  email: string;
  status?: string;
  consent_status?: string;
  consent_at?: string | null;
  consent_source?: string | null;
  consent_evidence_ref?: string | null;
  attributes?: Record<string, unknown>;
  tag_ids?: string[];
}

export interface ContactUpdateInput {
  status?: string;
  consent_status?: string;
  consent_at?: string | null;
  consent_source?: string | null;
  consent_evidence_ref?: string | null;
  attributes?: Record<string, unknown>;
}

export interface SuppressionCreateInput {
  email: string;
  reason: string;
  source?: string | null;
  occurred_at?: string | null;
  evidence?: Record<string, unknown> | null;
}

export interface SuppressionOut {
  id: string;
  normalized_email: string;
  reason: string;
  source: string | null;
  occurred_at: string;
  expires_at: string | null;
  evidence: Record<string, unknown> | null;
}

/* ----------------------------------------------------------------- segments */

export type SegmentMatch = "all" | "any";

/**
 * A stored condition in the validated AST (`app/domain/audience/segments.py`).
 * `key` is only meaningful for `attribute` conditions.
 */
export interface SegmentCondition {
  field: string;
  operator: string;
  key?: string;
  value?: unknown;
}

export interface SegmentDefinition {
  match: SegmentMatch;
  conditions: SegmentCondition[];
}

export interface SegmentOut {
  id: string;
  name: string;
  definition: SegmentDefinition;
  version: number;
  created_at: string;
  updated_at: string;
}

export interface SegmentEstimate {
  segment_id: string;
  match_count: number;
  eligible_count: number;
}

/* ------------------------------------------------------------------ imports */

export type MergePolicy = "skip" | "fill_missing" | "overwrite";

export const MERGE_POLICIES = ["skip", "fill_missing", "overwrite"] as const;

export interface ImportMapping {
  email: string;
  consent_status?: string;
  consent_at?: string;
  consent_source?: string;
  consent_evidence_ref?: string;
  attributes?: Record<string, string>;
}

export interface ImportCreated {
  import_id: string;
  status: string;
  upload_url: string;
  upload_expires_seconds: number;
}

export interface ImportOut {
  id: string;
  status: string;
  counts: Record<string, unknown> | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ImportPreviewRow {
  row_number: number;
  outcome: string;
  error_code: string | null;
}

export interface ImportPreview {
  import_id: string;
  status: string;
  counts: Record<string, number>;
  truncated: boolean;
  errors: ImportPreviewRow[];
  errors_truncated: boolean;
}

/* ---------------------------------------------------------------- campaigns */

export type RecipientStatus = "queued" | "retry" | "accepted" | "failed" | "skipped" | "unknown";

export const RECIPIENT_STATUSES = [
  "queued",
  "retry",
  "accepted",
  "failed",
  "skipped",
  "unknown",
] as const satisfies readonly RecipientStatus[];

export const CAMPAIGN_STATUSES = [
  "draft",
  "scheduled",
  "preparing",
  "sending",
  "paused",
  "completed",
  "cancelled",
  "failed",
] as const satisfies readonly CampaignStatus[];

/** Statuses whose draft fields the API still accepts (mirrors `EDITABLE_STATUSES`). */
export const CAMPAIGN_EDITABLE_STATUSES = ["draft", "scheduled"] as const;

export interface CampaignSummary {
  id: string;
  name: string;
  status: string;
  subject: string;
  from_name: string;
  from_email: string;
  template_id: string | null;
  template_version: number | null;
  segment_id: string | null;
  scheduled_at: string | null;
  scheduled_timezone: string | null;
  launched_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface CampaignOut extends CampaignSummary {
  reply_to: string | null;
  created_by: string | null;
}

export interface CampaignPage {
  items: CampaignSummary[];
  next_cursor: string | null;
  total: number;
}

export interface CampaignCreateInput {
  name: string;
  subject?: string;
  from_name?: string;
  from_email?: string;
  reply_to?: string | null;
  template_id?: string | null;
  segment_id?: string | null;
}

export interface CampaignUpdateInput {
  name?: string;
  subject?: string;
  from_name?: string;
  from_email?: string;
  reply_to?: string | null;
  template_id?: string | null;
  segment_id?: string | null;
}

export interface LaunchIssue {
  code: string;
  detail: string;
}

export interface LaunchValidationResult {
  campaign_id: string;
  ok: boolean;
  issues: LaunchIssue[];
}

export interface ScheduleRequestInput {
  scheduled_at?: string | null;
  timezone?: string | null;
  on_ambiguous?: string;
}

export interface ScheduleResult {
  campaign: CampaignOut;
  scheduled_at: string;
  timezone: string;
  /** ``unambiguous`` | ``ambiguous`` | ``nonexistent``. */
  resolution: string;
}

export interface LaunchResult {
  campaign_id: string;
  status: string;
  recipient_count: number;
  snapshot_version: number | null;
}

export interface RecipientOut {
  id: string;
  contact_id: string | null;
  email_snapshot: string;
  status: string;
  attempt_count: number;
  accepted_at: string | null;
  outcome_at: string | null;
  error_code: string | null;
  created_at: string;
}

export interface RecipientPage {
  items: RecipientOut[];
  next_cursor: string | null;
  total: number;
}

/* ---------------------------------------------------------------- analytics */

/**
 * Ledger state plus provider-reported totals.
 *
 * ``accepted`` is a *provider acceptance* and ``delivered`` is a
 * *provider-reported delivery*; they are never conflated, and a recipient whose
 * outcome is unresolved stays ``unknown`` (SPEC.md sections 7 and 10).
 */
export interface CampaignAnalytics {
  campaign_id: string;
  total_recipients: number;
  queued: number;
  accepted: number;
  failed: number;
  skipped: number;
  unknown: number;
  delivered: number;
  deferred: number;
  bounced: number;
  bounced_hard: number;
  bounced_soft: number;
  complained: number;
  unsubscribed: number;
  opened: number;
  clicked: number;
  caveats: string[];
}

/* ---------------------------------------------------------------- providers */

export type AccountStatus = "active" | "paused" | "disabled";

export const ACCOUNT_STATUSES = ["active", "paused", "disabled"] as const;

export type MessageClass = "marketing" | "transactional";

export const MESSAGE_CLASSES = ["marketing", "transactional"] as const;

export interface CredentialOut {
  id: string;
  label: string;
  key_version: number;
  status: string;
  created_at: string;
  rotated_at: string | null;
}

export interface ProviderAccountOut {
  id: string;
  provider: string;
  external_account_ref: string;
  display_name: string;
  status: string;
  eligible_message_classes: string[];
  sender_domains: string[];
  limits: Record<string, unknown>;
  quota_state: Record<string, unknown>;
  health_state: string;
  eligibility_verified_at: string | null;
  quota_refreshed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProviderAccountDetail extends ProviderAccountOut {
  credentials: CredentialOut[];
}

export interface ProviderAccountPage {
  items: ProviderAccountOut[];
  next_cursor: string | null;
  total: number;
}

export interface VerificationOut {
  valid: boolean;
  health_state: string;
  eligible_message_classes: string[];
  sender_domains: string[];
  /** ``adapter`` when the facts came from the provider, otherwise operator state. */
  observed_by: string;
  detail: string | null;
}

export interface VerifyResult {
  account: ProviderAccountOut;
  verification: VerificationOut;
}

export interface CapacityOut {
  observed_at: string;
  source: string;
  daily_limit: number | null;
  daily_used: number | null;
  monthly_limit: number | null;
  monthly_used: number | null;
  rate_per_second: number | null;
  notes: string | null;
}

export interface CapacityRefreshResult {
  account: ProviderAccountOut;
  capacity: CapacityOut;
}

export interface RoutingExclusion {
  account_id: string;
  provider: string;
  reason: string;
  detail: string | null;
}

export interface RoutingStatus {
  marketing_paused: boolean;
  paused_reason: string | null;
  marketing_eligible: boolean;
  capacity_fresh: boolean;
  exclusions: RoutingExclusion[];
}

export interface ProviderAccountCreateInput {
  provider: string;
  external_account_ref: string;
  display_name?: string;
  eligible_message_classes?: string[];
  sender_domains?: string[];
  routing_priority?: number | null;
  routing_weight?: number | null;
  /** Write-only: the API stores an encrypted envelope and never returns it. */
  secret: string;
  secret_label?: string;
}

export interface ProviderAccountUpdateInput {
  display_name?: string;
  status?: string;
  eligible_message_classes?: string[];
  sender_domains?: string[];
  routing_priority?: number | null;
  routing_weight?: number | null;
}
