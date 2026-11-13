"use client";

/**
 * Shared presentation primitives.
 *
 * The app deliberately keeps its own small style sheet instead of pulling in a
 * UI framework: every page uses the same inline `styles` object so the
 * operator-facing screens stay visually consistent.
 */

import type { CSSProperties, ReactNode } from "react";
import { ApiError } from "@email-platform/api-client";

export const styles: Record<string, CSSProperties> = {
  header: { marginBottom: 20 },
  headerRow: {
    display: "flex",
    alignItems: "flex-start",
    justifyContent: "space-between",
    gap: 12,
    flexWrap: "wrap",
  },
  h1: { margin: "0 0 4px", fontSize: 22 },
  subtitle: { margin: 0, color: "#9aa4b2", fontSize: 13, lineHeight: 1.5 },
  h2: { margin: "0 0 4px", fontSize: 15 },
  row: { display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" },
  inlineGroup: { display: "flex", gap: 6, alignItems: "center", flexWrap: "wrap" },
  card: {
    border: "1px solid #2a2f3a",
    borderRadius: 8,
    padding: 16,
    background: "#10141c",
    marginBottom: 16,
  },
  cardList: { listStyle: "none", padding: 0, margin: "12px 0 0" },
  hint: { margin: "4px 0 12px", color: "#9aa4b2", fontSize: 12, lineHeight: 1.5 },
  field: { display: "block", marginBottom: 10 },
  fieldLabel: { display: "block", fontSize: 12, color: "#9aa4b2", marginBottom: 4 },
  input: {
    width: "100%",
    padding: "7px 9px",
    background: "#141822",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
    boxSizing: "border-box",
  },
  select: {
    padding: "7px 9px",
    background: "#141822",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
  },
  textarea: {
    width: "100%",
    minHeight: 96,
    padding: "7px 9px",
    background: "#141822",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
    boxSizing: "border-box",
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace",
    fontSize: 12,
  },
  primary: {
    padding: "7px 14px",
    background: "#2f6feb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
  },
  secondary: {
    padding: "7px 14px",
    background: "#1b2130",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
    cursor: "pointer",
  },
  danger: {
    padding: "7px 14px",
    background: "transparent",
    color: "#ff8a8a",
    border: "1px solid #5c2b2b",
    borderRadius: 6,
    cursor: "pointer",
  },
  link: { background: "none", border: "none", padding: 0, color: "#6ea8fe", cursor: "pointer", fontSize: 13 },
  error: { color: "#ff8a8a", fontSize: 13, margin: "8px 0 0" },
  warning: { color: "#e3b341", fontSize: 13, margin: "8px 0 0" },
  notice: { color: "#6fcf97", fontSize: 13, margin: "8px 0 0" },
  muted: { color: "#9aa4b2", fontSize: 13 },
  mono: { fontFamily: "ui-monospace, SFMono-Regular, Menlo, monospace", fontSize: 12 },
  table: { width: "100%", borderCollapse: "collapse", fontSize: 13, marginTop: 8 },
  th: {
    textAlign: "left",
    padding: "8px 10px",
    borderBottom: "1px solid #2a2f3a",
    color: "#9aa4b2",
    fontWeight: 500,
    whiteSpace: "nowrap",
  },
  td: { padding: "8px 10px", borderBottom: "1px solid #1b2130", verticalAlign: "top" },
  statGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
    gap: 10,
    marginTop: 12,
  },
  stat: {
    border: "1px solid #2a2f3a",
    borderRadius: 8,
    padding: "10px 12px",
    background: "#0f131a",
  },
  statValue: { fontSize: 20, fontWeight: 600, lineHeight: 1.2 },
  statLabel: { fontSize: 12, color: "#9aa4b2" },
  statHint: { fontSize: 11, color: "#6d7684", marginTop: 2 },
  pill: {
    display: "inline-block",
    padding: "2px 8px",
    borderRadius: 999,
    border: "1px solid #2a2f3a",
    fontSize: 11,
    color: "#c8d0dc",
    whiteSpace: "nowrap",
  },
  chips: { display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 },
  chip: {
    padding: "2px 8px",
    fontSize: 11,
    border: "1px solid #2a2f3a",
    borderRadius: 999,
    color: "#9aa4b2",
  },
  pre: {
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    background: "#0b0d12",
    padding: 10,
    borderRadius: 6,
    color: "#c8d0dc",
    fontSize: 12,
    margin: "8px 0 0",
  },
  checkbox: { display: "flex", gap: 6, alignItems: "center", fontSize: 13 },
  divider: { border: 0, borderTop: "1px solid #2a2f3a", margin: "16px 0" },
};

/** Render an ISO timestamp in the operator's own locale, tolerating nulls. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "—";
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

/** Convert an ISO timestamp to the value a `datetime-local` input expects. */
export function toDateTimeLocal(value: string | null | undefined): string {
  if (!value) {
    return "";
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return "";
  }
  const pad = (part: number) => String(part).padStart(2, "0");
  return [
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}`,
    `${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`,
  ].join("T");
}

/** Convert a `datetime-local` value to an ISO instant (or null when empty). */
export function fromDateTimeLocal(value: string): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}

/** Parse a JSON object from a textarea, rejecting arrays and scalars. */
export function parseJsonObject(text: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) {
    return {};
  }
  const parsed = JSON.parse(trimmed) as unknown;
  if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
    throw new Error("Expected a JSON object");
  }
  return parsed as Record<string, unknown>;
}

/** Split a comma-separated input into trimmed, non-empty values. */
export function splitList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

export function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.body.reason;
    const allowed = error.body.allowed;
    if (typeof reason === "string") {
      const suffix = Array.isArray(allowed) ? ` — allowed: ${allowed.join(", ")}` : "";
      return `${error.message} (${reason})${suffix}`;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

export function PageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header style={styles.header}>
      <div style={styles.headerRow}>
        <div>
          <h1 style={styles.h1}>{title}</h1>
          {description ? <p style={styles.subtitle}>{description}</p> : null}
        </div>
        {actions ? <div style={styles.inlineGroup}>{actions}</div> : null}
      </div>
    </header>
  );
}

export function Card({
  title,
  description,
  actions,
  children,
}: {
  title?: string;
  description?: ReactNode;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section style={styles.card}>
      {title || actions ? (
        <div style={styles.headerRow}>
          <div>
            {title ? <h2 style={styles.h2}>{title}</h2> : null}
            {description ? <p style={styles.hint}>{description}</p> : null}
          </div>
          {actions ? <div style={styles.inlineGroup}>{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <label style={styles.field}>
      <span style={styles.fieldLabel}>{label}</span>
      {children}
      {hint ? <span style={styles.hint}>{hint}</span> : null}
    </label>
  );
}

/**
 * Like {@link Field} but without the wrapping `label`, for groups whose children
 * are themselves labelable controls (checkbox lists, repeated rows).
 */
export function Fieldset({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div style={styles.field}>
      <span style={styles.fieldLabel}>{label}</span>
      {children}
      {hint ? <span style={styles.hint}>{hint}</span> : null}
    </div>
  );
}

export function Note({
  tone = "notice",
  children,
}: {
  tone?: "error" | "notice" | "warning";
  children: ReactNode;
}) {
  return <p style={styles[tone]}>{children}</p>;
}

export function StatusPill({ label }: { label: string }) {
  return <span style={styles.pill}>{label}</span>;
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: number | string;
  hint?: string;
}) {
  return (
    <div style={styles.stat}>
      <div style={styles.statValue}>{value}</div>
      <div style={styles.statLabel}>{label}</div>
      {hint ? <div style={styles.statHint}>{hint}</div> : null}
    </div>
  );
}
