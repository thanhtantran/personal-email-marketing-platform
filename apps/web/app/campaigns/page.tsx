"use client";

/**
 * Campaign list with an inline draft creator.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  CAMPAIGN_STATUSES,
  createCampaign,
  listCampaigns,
  listSegments,
  listTemplates,
  type CampaignPage,
  type SegmentOut,
  type TemplateSummary,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Note,
  PageHeader,
  StatusPill,
  describeError,
  formatDateTime,
  styles,
} from "@/components/ui";

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `campaign-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function CampaignsPage() {
  const [page, setPage] = useState<CampaignPage | null>(null);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [segments, setSegments] = useState<SegmentOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [statusFilter, setStatusFilter] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([]);

  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [fromName, setFromName] = useState("");
  const [fromEmail, setFromEmail] = useState("");
  const [replyTo, setReplyTo] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [segmentId, setSegmentId] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listCampaigns(
      { limit: 25, cursor, status: statusFilter || undefined },
      controller.signal,
    )
      .then(setPage)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    return () => controller.abort();
  }, [cursor, statusFilter, reloadToken]);

  useEffect(() => {
    const controller = new AbortController();
    listTemplates(controller.signal)
      .then(setTemplates)
      .catch(() => undefined);
    listSegments(controller.signal)
      .then(setSegments)
      .catch(() => undefined);
    return () => controller.abort();
  }, [reloadToken]);

  function goNext() {
    if (!page?.next_cursor) {
      return;
    }
    setCursorHistory([...cursorHistory, cursor]);
    setCursor(page.next_cursor);
  }

  function goBack() {
    if (cursorHistory.length === 0) {
      return;
    }
    const previous = cursorHistory[cursorHistory.length - 1] ?? null;
    setCursorHistory(cursorHistory.slice(0, -1));
    setCursor(previous);
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const campaign = await createCampaign(
        {
          name,
          subject,
          from_name: fromName,
          from_email: fromEmail,
          reply_to: replyTo || null,
          template_id: templateId || null,
          segment_id: segmentId || null,
        },
        newIdempotencyKey(),
      );
      setNotice(`Created campaign ${campaign.name}.`);
      setName("");
      setSubject("");
      setFromName("");
      setFromEmail("");
      setReplyTo("");
      setTemplateId("");
      setSegmentId("");
      setCursor(null);
      setCursorHistory([]);
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <PageHeader
        title="Campaigns"
        description="Draft, schedule and launch sends. Content and audience freeze at launch."
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card title="New campaign">
        <form onSubmit={handleCreate}>
          <div style={styles.row}>
            <Field label="Name">
              <input
                style={styles.input}
                required
                value={name}
                onChange={(event) => setName(event.target.value)}
              />
            </Field>
            <Field label="Subject">
              <input
                style={styles.input}
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
              />
            </Field>
          </div>
          <div style={styles.row}>
            <Field label="From name">
              <input
                style={styles.input}
                value={fromName}
                onChange={(event) => setFromName(event.target.value)}
              />
            </Field>
            <Field label="From email">
              <input
                style={styles.input}
                type="email"
                value={fromEmail}
                onChange={(event) => setFromEmail(event.target.value)}
              />
            </Field>
            <Field label="Reply-to">
              <input
                style={styles.input}
                type="email"
                value={replyTo}
                onChange={(event) => setReplyTo(event.target.value)}
              />
            </Field>
          </div>
          <div style={styles.row}>
            <Field label="Template">
              <select
                style={styles.select}
                value={templateId}
                onChange={(event) => setTemplateId(event.target.value)}
              >
                <option value="">none</option>
                {templates.map((template) => (
                  <option key={template.id} value={template.id}>
                    {template.name} (v{template.version})
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Segment">
              <select
                style={styles.select}
                value={segmentId}
                onChange={(event) => setSegmentId(event.target.value)}
              >
                <option value="">none</option>
                {segments.map((segment) => (
                  <option key={segment.id} value={segment.id}>
                    {segment.name}
                  </option>
                ))}
              </select>
            </Field>
          </div>
          <button type="submit" style={styles.primary} disabled={busy}>
            Create campaign
          </button>
        </form>
      </Card>

      <Card
        title={page ? `Campaigns (${page.total})` : "Campaigns"}
        actions={
          <span style={styles.inlineGroup}>
            <select
              style={styles.select}
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setCursor(null);
                setCursorHistory([]);
              }}
            >
              <option value="">any status</option>
              {CAMPAIGN_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <button
              type="button"
              style={styles.secondary}
              onClick={goBack}
              disabled={cursorHistory.length === 0}
            >
              Back
            </button>
            <button
              type="button"
              style={styles.secondary}
              onClick={goNext}
              disabled={!page?.next_cursor}
            >
              Next
            </button>
          </span>
        }
      >
        {page === null ? (
          <p style={styles.muted}>Loading…</p>
        ) : page.items.length === 0 ? (
          <p style={styles.muted}>No campaigns yet.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Subject</th>
                <th style={styles.th}>Scheduled</th>
                <th style={styles.th}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((campaign) => (
                <tr key={campaign.id}>
                  <td style={styles.td}>
                    <Link href={`/campaigns/${campaign.id}`}>{campaign.name}</Link>
                  </td>
                  <td style={styles.td}>
                    <StatusPill label={campaign.status} />
                  </td>
                  <td style={styles.td}>{campaign.subject || "—"}</td>
                  <td style={styles.td}>{formatDateTime(campaign.scheduled_at)}</td>
                  <td style={styles.td}>{formatDateTime(campaign.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}
