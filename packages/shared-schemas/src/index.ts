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
