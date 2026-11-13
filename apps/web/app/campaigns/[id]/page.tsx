"use client";

/**
 * Campaign detail: draft editing, the launch gate, scheduling, lifecycle
 * controls, the frozen recipient ledger and campaign analytics.
 *
 * ``accepted`` (provider acceptance) and ``delivered`` (provider-reported
 * delivery) are shown as separate numbers on purpose, and unresolved recipients
 * stay ``unknown`` rather than being assumed delivered.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  RECIPIENT_STATUSES,
  cancelCampaign,
  getCampaign,
  getCampaignAnalytics,
  launchCampaign,
  listRecipients,
  listSegments,
  listTemplates,
  pauseCampaign,
  resumeCampaign,
  scheduleCampaign,
  updateCampaign,
  validateCampaign,
  type CampaignAnalytics,
  type CampaignOut,
  type LaunchValidationResult,
  type RecipientPage,
  type SegmentOut,
  type TemplateSummary,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Note,
  PageHeader,
  Stat,
  StatusPill,
  describeError,
  formatDateTime,
  styles,
} from "@/components/ui";

const AMBIGUOUS_POLICIES = ["earliest", "latest"] as const;

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `launch-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function CampaignDetailPage() {
  const { id } = useParams<{ id: string }>();

  const [campaign, setCampaign] = useState<CampaignOut | null>(null);
  const [templates, setTemplates] = useState<TemplateSummary[]>([]);
  const [segments, setSegments] = useState<SegmentOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [name, setName] = useState("");
  const [subject, setSubject] = useState("");
  const [fromName, setFromName] = useState("");
  const [fromEmail, setFromEmail] = useState("");
  const [replyTo, setReplyTo] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [segmentId, setSegmentId] = useState("");

  const [validation, setValidation] = useState<LaunchValidationResult | null>(null);
  const [scheduledAt, setScheduledAt] = useState("");
  const [timezone, setTimezone] = useState("");
  const [onAmbiguous, setOnAmbiguous] = useState<string>("earliest");

  const [recipientPage, setRecipientPage] = useState<RecipientPage | null>(null);
  const [recipientStatus, setRecipientStatus] = useState("");
  const [recipientCursor, setRecipientCursor] = useState<string | null>(null);
  const [recipientHistory, setRecipientHistory] = useState<(string | null)[]>([]);

  const [analytics, setAnalytics] = useState<CampaignAnalytics | null>(null);

  useEffect(() => {
    setTimezone(Intl.DateTimeFormat().resolvedOptions().timeZone);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    getCampaign(id, controller.signal)
      .then((loaded) => {
        setCampaign(loaded);
        setName(loaded.name);
        setSubject(loaded.subject);
        setFromName(loaded.from_name);
        setFromEmail(loaded.from_email);
        setReplyTo(loaded.reply_to ?? "");
        setTemplateId(loaded.template_id ?? "");
        setSegmentId(loaded.segment_id ?? "");
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    listTemplates(controller.signal)
      .then(setTemplates)
      .catch(() => undefined);
    listSegments(controller.signal)
      .then(setSegments)
      .catch(() => undefined);
    getCampaignAnalytics(id, controller.signal)
      .then(setAnalytics)
      .catch(() => undefined);
    return () => controller.abort();
  }, [id, reloadToken]);

  useEffect(() => {
    const controller = new AbortController();
    listRecipients(
      id,
      { limit: 25, cursor: recipientCursor, status: recipientStatus || undefined },
      controller.signal,
    )
      .then(setRecipientPage)
      .catch(() => undefined);
    return () => controller.abort();
  }, [id, recipientCursor, recipientStatus, reloadToken]);

  async function run<T>(action: () => Promise<T>, onSuccess?: (value: T) => void) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const value = await action();
      onSuccess?.(value);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  function refresh() {
    setReloadToken((token) => token + 1);
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    await run(
      () =>
        updateCampaign(id, {
          name,
          subject,
          from_name: fromName,
          from_email: fromEmail,
          reply_to: replyTo || null,
          template_id: templateId || null,
          segment_id: segmentId || null,
        }),
      (updated) => {
        setCampaign(updated);
        setNotice("Campaign draft saved.");
      },
    );
  }

  if (error && !campaign) {
    return (
      <main>
        <Note tone="error">{error}</Note>
        <Link href="/campaigns">Back to campaigns</Link>
      </main>
    );
  }

  if (!campaign) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  const editable = campaign.status === "draft" || campaign.status === "scheduled";
  const canPause = campaign.status === "preparing" || campaign.status === "sending";
  const canResume = campaign.status === "paused";
  const canCancel = !["completed", "cancelled", "failed"].includes(campaign.status);

  return (
    <main>
      <PageHeader
        title={campaign.name}
        description={
          <>
            <StatusPill label={campaign.status} /> {campaign.subject || "no subject"}
          </>
        }
        actions={<Link href="/campaigns">Back to campaigns</Link>}
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card title="Overview">
        <table style={styles.table}>
          <tbody>
            <tr>
              <td style={styles.td}>Status</td>
              <td style={styles.td}>
                <StatusPill label={campaign.status} />
              </td>
            </tr>
            <tr>
              <td style={styles.td}>From</td>
              <td style={styles.td}>
                {campaign.from_name} &lt;{campaign.from_email}&gt;
              </td>
            </tr>
            <tr>
              <td style={styles.td}>Reply-to</td>
              <td style={styles.td}>{campaign.reply_to ?? "—"}</td>
            </tr>
            <tr>
              <td style={styles.td}>Template</td>
              <td style={styles.td}>
                {campaign.template_id ? (
                  <Link href={`/templates/${campaign.template_id}`}>
                    {campaign.template_id} (v{campaign.template_version ?? "?"})
                  </Link>
                ) : (
                  "—"
                )}
              </td>
            </tr>
            <tr>
              <td style={styles.td}>Segment</td>
              <td style={styles.td}>{campaign.segment_id ?? "—"}</td>
            </tr>
            <tr>
              <td style={styles.td}>Scheduled</td>
              <td style={styles.td}>
                {formatDateTime(campaign.scheduled_at)} {campaign.scheduled_timezone ?? ""}
              </td>
            </tr>
            <tr>
              <td style={styles.td}>Launched</td>
              <td style={styles.td}>{formatDateTime(campaign.launched_at)}</td>
            </tr>
          </tbody>
        </table>
      </Card>

      {editable ? (
        <Card title="Edit draft">
          <form onSubmit={handleSave}>
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
              Save draft
            </button>
          </form>
        </Card>
      ) : (
        <Card title="Edit draft">
          <p style={styles.muted}>
            Content and audience are frozen once a campaign leaves draft or scheduled state.
          </p>
        </Card>
      )}

      <Card
        title="Launch gate"
        description="Validation is a dry run: it never freezes content or enqueues recipients."
        actions={
          <span style={styles.inlineGroup}>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => run(() => validateCampaign(id), setValidation)}
              disabled={busy}
            >
              Validate
            </button>
            <button
              type="button"
              style={styles.primary}
              onClick={() =>
                run(
                  () => launchCampaign(id, newIdempotencyKey()),
                  (result) => {
                    setNotice(
                      `Launch accepted: ${result.status}, ${result.recipient_count} recipient(s), snapshot v${result.snapshot_version ?? "?"}.`,
                    );
                    refresh();
                  },
                )
              }
              disabled={busy || !editable}
            >
              Launch now
            </button>
          </span>
        }
      >
        {validation === null ? (
          <p style={styles.muted}>Run validation to see launch blockers.</p>
        ) : (
          <>
            <Note tone={validation.ok ? "notice" : "warning"}>
              {validation.ok ? "Ready to launch." : `${validation.issues.length} blocking issue(s).`}
            </Note>
            {validation.issues.length > 0 ? (
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Code</th>
                    <th style={styles.th}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.issues.map((issue) => (
                    <tr key={issue.code}>
                      <td style={{ ...styles.td, ...styles.mono }}>{issue.code}</td>
                      <td style={styles.td}>{issue.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </>
        )}
      </Card>

      <Card
        title="Schedule"
        description="Provide a wall-clock time in the chosen timezone, or leave it empty to launch as soon as possible."
      >
        <div style={styles.row}>
          <Field label="Scheduled at">
            <input
              style={styles.input}
              type="datetime-local"
              value={scheduledAt}
              onChange={(event) => setScheduledAt(event.target.value)}
            />
          </Field>
          <Field label="Timezone">
            <input
              style={styles.input}
              value={timezone}
              onChange={(event) => setTimezone(event.target.value)}
              placeholder="Asia/Shanghai"
            />
          </Field>
          <Field label="On ambiguous">
            <select
              style={styles.select}
              value={onAmbiguous}
              onChange={(event) => setOnAmbiguous(event.target.value)}
            >
              {AMBIGUOUS_POLICIES.map((policy) => (
                <option key={policy} value={policy}>
                  {policy}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            style={styles.secondary}
            onClick={() =>
              run(
                () =>
                  scheduleCampaign(id, {
                    scheduled_at: scheduledAt || null,
                    timezone: timezone || null,
                    on_ambiguous: onAmbiguous,
                  }),
                (result) => {
                  setNotice(
                    `Scheduled for ${formatDateTime(result.scheduled_at)} (${result.timezone}, ${result.resolution}).`,
                  );
                  refresh();
                },
              )
            }
            disabled={busy || !editable}
          >
            Schedule
          </button>
        </div>
      </Card>

      <Card title="Lifecycle">
        <span style={styles.inlineGroup}>
          <button
            type="button"
            style={styles.secondary}
            onClick={() => run(() => pauseCampaign(id), refresh)}
            disabled={busy || !canPause}
          >
            Pause
          </button>
          <button
            type="button"
            style={styles.secondary}
            onClick={() => run(() => resumeCampaign(id), refresh)}
            disabled={busy || !canResume}
          >
            Resume
          </button>
          <button
            type="button"
            style={styles.danger}
            onClick={() => run(() => cancelCampaign(id), refresh)}
            disabled={busy || !canCancel}
          >
            Cancel
          </button>
        </span>
      </Card>

      <Card
        title={analytics ? `Analytics (${analytics.total_recipients} recipient(s))` : "Analytics"}
        actions={
          <button
            type="button"
            style={styles.secondary}
            onClick={() =>
              run(
                () => getCampaignAnalytics(id),
                (value) => setAnalytics(value),
              )
            }
            disabled={busy}
          >
            Refresh
          </button>
        }
      >
        {analytics === null ? (
          <p style={styles.muted}>No analytics yet.</p>
        ) : (
          <>
            <div style={styles.statGrid}>
              <Stat label="Total" value={analytics.total_recipients} />
              <Stat label="Queued" value={analytics.queued} />
              <Stat
                label="Accepted"
                value={analytics.accepted}
                hint="Provider accepted the send"
              />
              <Stat
                label="Delivered"
                value={analytics.delivered}
                hint="Provider-reported delivery"
              />
              <Stat label="Deferred" value={analytics.deferred} />
              <Stat label="Failed" value={analytics.failed} />
              <Stat label="Skipped" value={analytics.skipped} />
              <Stat label="Unknown" value={analytics.unknown} hint="Outcome unresolved" />
              <Stat label="Bounced" value={analytics.bounced} hint={`hard ${analytics.bounced_hard} · soft ${analytics.bounced_soft}`} />
              <Stat label="Complained" value={analytics.complained} />
              <Stat label="Unsubscribed" value={analytics.unsubscribed} />
              <Stat label="Opened" value={analytics.opened} />
              <Stat label="Clicked" value={analytics.clicked} />
            </div>
            {analytics.caveats.length > 0 ? (
              <ul style={styles.hint}>
                {analytics.caveats.map((caveat) => (
                  <li key={caveat}>{caveat}</li>
                ))}
              </ul>
            ) : null}
          </>
        )}
      </Card>

      <Card
        title={recipientPage ? `Recipients (${recipientPage.total})` : "Recipients"}
        actions={
          <span style={styles.inlineGroup}>
            <select
              style={styles.select}
              value={recipientStatus}
              onChange={(event) => {
                setRecipientStatus(event.target.value);
                setRecipientCursor(null);
                setRecipientHistory([]);
              }}
            >
              <option value="">any status</option>
              {RECIPIENT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => {
                if (recipientHistory.length === 0) {
                  return;
                }
                const previous = recipientHistory[recipientHistory.length - 1] ?? null;
                setRecipientHistory(recipientHistory.slice(0, -1));
                setRecipientCursor(previous);
              }}
              disabled={recipientHistory.length === 0}
            >
              Back
            </button>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => {
                if (!recipientPage?.next_cursor) {
                  return;
                }
                setRecipientHistory([...recipientHistory, recipientCursor]);
                setRecipientCursor(recipientPage.next_cursor);
              }}
              disabled={!recipientPage?.next_cursor}
            >
              Next
            </button>
          </span>
        }
      >
        {recipientPage === null ? (
          <p style={styles.muted}>Loading…</p>
        ) : recipientPage.items.length === 0 ? (
          <p style={styles.muted}>
            No recipients. The ledger is written when the campaign launches.
          </p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Attempts</th>
                <th style={styles.th}>Accepted</th>
                <th style={styles.th}>Outcome</th>
                <th style={styles.th}>Error</th>
              </tr>
            </thead>
            <tbody>
              {recipientPage.items.map((recipient) => (
                <tr key={recipient.id}>
                  <td style={styles.td}>{recipient.email_snapshot}</td>
                  <td style={styles.td}>
                    <StatusPill label={recipient.status} />
                  </td>
                  <td style={styles.td}>{recipient.attempt_count}</td>
                  <td style={styles.td}>{formatDateTime(recipient.accepted_at)}</td>
                  <td style={styles.td}>{formatDateTime(recipient.outcome_at)}</td>
                  <td style={styles.td}>{recipient.error_code ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}
