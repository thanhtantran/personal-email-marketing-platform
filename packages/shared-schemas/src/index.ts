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
