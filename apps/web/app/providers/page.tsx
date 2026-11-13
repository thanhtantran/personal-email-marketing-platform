"use client";

/**
 * Provider accounts and the marketing routing control.
 *
 * Routing state explains *why* marketing traffic can or cannot send right now;
 * pausing marketing is independent of an individual account's status.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  ACCOUNT_STATUSES,
  MESSAGE_CLASSES,
  createProviderAccount,
  getRoutingStatus,
  listProviderAccounts,
  setRoutingPause,
  type ProviderAccountPage,
  type RoutingStatus,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Fieldset,
  Note,
  PageHeader,
  StatusPill,
  describeError,
  splitList,
  styles,
} from "@/components/ui";

function parseOptionalNumber(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export default function ProvidersPage() {
  const [page, setPage] = useState<ProviderAccountPage | null>(null);
  const [routing, setRouting] = useState<RoutingStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [statusFilter, setStatusFilter] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([]);
  const [pauseReason, setPauseReason] = useState("");

  const [provider, setProvider] = useState("");
  const [externalRef, setExternalRef] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [classes, setClasses] = useState<string[]>(["marketing"]);
  const [domains, setDomains] = useState("");
  const [priority, setPriority] = useState("");
  const [weight, setWeight] = useState("");
  const [secret, setSecret] = useState("");
  const [secretLabel, setSecretLabel] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    listProviderAccounts(
      { limit: 25, cursor, status: statusFilter || undefined },
      controller.signal,
    )
      .then(setPage)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    getRoutingStatus(controller.signal)
      .then(setRouting)
      .catch(() => undefined);
    return () => controller.abort();
  }, [cursor, statusFilter, reloadToken]);

  async function run(action: () => Promise<unknown>, success?: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      if (success) {
        setNotice(success);
      }
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      await createProviderAccount({
        provider,
        external_account_ref: externalRef,
        display_name: displayName,
        eligible_message_classes: classes,
        sender_domains: splitList(domains),
        routing_priority: parseOptionalNumber(priority),
        routing_weight: parseOptionalNumber(weight),
        secret,
        secret_label: secretLabel,
      });
      setProvider("");
      setExternalRef("");
      setDisplayName("");
      setClasses(["marketing"]);
      setDomains("");
      setPriority("");
      setWeight("");
      setSecret("");
      setSecretLabel("");
    }, "Provider account created.");
  }

  return (
    <main>
      <PageHeader
        title="Providers"
        description="Sending accounts, credentials and the marketing routing switch."
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card
        title="Marketing routing"
        actions={
          <span style={styles.inlineGroup}>
            <input
              style={styles.input}
              placeholder="pause reason"
              value={pauseReason}
              onChange={(event) => setPauseReason(event.target.value)}
            />
            <button
              type="button"
              style={styles.danger}
              onClick={() => run(() => setRoutingPause(true, pauseReason || undefined), "Marketing paused.")}
              disabled={busy || routing?.marketing_paused === true}
            >
              Pause marketing
            </button>
            <button
              type="button"
              style={styles.primary}
              onClick={() => run(() => setRoutingPause(false), "Marketing resumed.")}
              disabled={busy || routing?.marketing_paused === false}
            >
              Resume marketing
            </button>
          </span>
        }
      >
        {routing === null ? (
          <p style={styles.muted}>Loading…</p>
        ) : (
          <>
            <p style={styles.muted}>
              {routing.marketing_paused ? "Paused" : "Active"} ·{" "}
              {routing.marketing_eligible ? "eligible" : "not eligible"} · capacity{" "}
              {routing.capacity_fresh ? "fresh" : "stale"}
              {routing.paused_reason ? ` · reason: ${routing.paused_reason}` : ""}
            </p>
            {routing.exclusions.length > 0 ? (
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Provider</th>
                    <th style={styles.th}>Reason</th>
                    <th style={styles.th}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {routing.exclusions.map((exclusion) => (
                    <tr key={`${exclusion.account_id}-${exclusion.reason}`}>
                      <td style={styles.td}>{exclusion.provider}</td>
                      <td style={styles.td}>{exclusion.reason}</td>
                      <td style={styles.td}>{exclusion.detail ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p style={styles.muted}>No routing exclusions.</p>
            )}
          </>
        )}
      </Card>

      <Card title="New provider account">
        <form onSubmit={handleCreate}>
          <div style={styles.row}>
            <Field label="Provider" hint="e.g. ses, sendgrid">
              <input
                style={styles.input}
                required
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
              />
            </Field>
            <Field label="External account ref">
              <input
                style={styles.input}
                required
                value={externalRef}
                onChange={(event) => setExternalRef(event.target.value)}
              />
            </Field>
            <Field label="Display name">
              <input
                style={styles.input}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
          </div>
          <div style={styles.row}>
            <Fieldset label="Message classes">
              <span style={styles.chips}>
                {MESSAGE_CLASSES.map((messageClass) => (
                  <label key={messageClass} style={styles.checkbox}>
                    <input
                      type="checkbox"
                      checked={classes.includes(messageClass)}
                      onChange={(event) =>
                        setClasses((current) =>
                          event.target.checked
                            ? [...current, messageClass]
                            : current.filter((value) => value !== messageClass),
                        )
                      }
                    />
                    {messageClass}
                  </label>
                ))}
              </span>
            </Fieldset>
            <Field label="Sender domains" hint="Comma-separated">
              <input
                style={styles.input}
                value={domains}
                onChange={(event) => setDomains(event.target.value)}
                placeholder="example.com, mail.example.com"
              />
            </Field>
          </div>
          <div style={styles.row}>
            <Field label="Routing priority">
              <input
                style={styles.input}
                type="number"
                value={priority}
                onChange={(event) => setPriority(event.target.value)}
              />
            </Field>
            <Field label="Routing weight">
              <input
                style={styles.input}
                type="number"
                value={weight}
                onChange={(event) => setWeight(event.target.value)}
              />
            </Field>
            <Field label="Secret" hint="Write-only; stored encrypted and never returned.">
              <input
                style={styles.input}
                required
                type="password"
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
              />
            </Field>
            <Field label="Secret label">
              <input
                style={styles.input}
                value={secretLabel}
                onChange={(event) => setSecretLabel(event.target.value)}
              />
            </Field>
          </div>
          <button type="submit" style={styles.primary} disabled={busy}>
            Create account
          </button>
        </form>
      </Card>

      <Card
        title={page ? `Accounts (${page.total})` : "Accounts"}
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
              {ACCOUNT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => {
                if (cursorHistory.length === 0) {
                  return;
                }
                const previous = cursorHistory[cursorHistory.length - 1] ?? null;
                setCursorHistory(cursorHistory.slice(0, -1));
                setCursor(previous);
              }}
              disabled={cursorHistory.length === 0}
            >
              Back
            </button>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => {
                if (!page?.next_cursor) {
                  return;
                }
                setCursorHistory([...cursorHistory, cursor]);
                setCursor(page.next_cursor);
              }}
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
          <p style={styles.muted}>No provider accounts yet.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Display name</th>
                <th style={styles.th}>Provider</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Classes</th>
                <th style={styles.th}>Health</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((account) => (
                <tr key={account.id}>
                  <td style={styles.td}>
                    <Link href={`/providers/${account.id}`}>
                      {account.display_name || account.external_account_ref}
                    </Link>
                  </td>
                  <td style={styles.td}>{account.provider}</td>
                  <td style={styles.td}>
                    <StatusPill label={account.status} />
                  </td>
                  <td style={styles.td}>{account.eligible_message_classes.join(", ") || "—"}</td>
                  <td style={styles.td}>{account.health_state}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}
