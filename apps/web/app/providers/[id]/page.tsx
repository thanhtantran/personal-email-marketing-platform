"use client";

/**
 * Provider account detail: eligibility facts, capacity, credentials and
 * verification. A credential secret is write-only; the API never echoes it.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ACCOUNT_STATUSES,
  MESSAGE_CLASSES,
  addProviderCredential,
  getProviderAccount,
  refreshProviderAccountCapacity,
  revokeProviderCredential,
  updateProviderAccount,
  verifyProviderAccount,
  type CapacityRefreshResult,
  type ProviderAccountDetail,
  type VerifyResult,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Fieldset,
  Note,
  PageHeader,
  Stat,
  StatusPill,
  describeError,
  formatDateTime,
  splitList,
  styles,
} from "@/components/ui";

export default function ProviderDetailPage() {
  const { id } = useParams<{ id: string }>();

  const [account, setAccount] = useState<ProviderAccountDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [displayName, setDisplayName] = useState("");
  const [status, setStatus] = useState("active");
  const [classes, setClasses] = useState<string[]>([]);
  const [domains, setDomains] = useState("");

  const [verification, setVerification] = useState<VerifyResult | null>(null);
  const [capacity, setCapacity] = useState<CapacityRefreshResult | null>(null);

  const [secret, setSecret] = useState("");
  const [secretLabel, setSecretLabel] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getProviderAccount(id, controller.signal)
      .then((loaded) => {
        setAccount(loaded);
        setDisplayName(loaded.display_name);
        setStatus(loaded.status);
        setClasses(loaded.eligible_message_classes);
        setDomains(loaded.sender_domains.join(", "));
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    return () => controller.abort();
  }, [id, reloadToken]);

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

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    await run(
      () =>
        updateProviderAccount(id, {
          display_name: displayName,
          status,
          eligible_message_classes: classes,
          sender_domains: splitList(domains),
        }),
      "Account updated.",
    );
  }

  async function handleAddCredential(event: FormEvent) {
    event.preventDefault();
    await run(async () => {
      await addProviderCredential(id, secret, secretLabel);
      setSecret("");
      setSecretLabel("");
    }, "Credential stored.");
  }

  if (error && !account) {
    return (
      <main>
        <Note tone="error">{error}</Note>
        <Link href="/providers">Back to providers</Link>
      </main>
    );
  }

  if (!account) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main>
      <PageHeader
        title={account.display_name || account.external_account_ref}
        description={
          <>
            {account.provider} · <StatusPill label={account.status} /> health {account.health_state}
          </>
        }
        actions={<Link href="/providers">Back to providers</Link>}
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card
        title="Account"
        actions={
          <span style={styles.inlineGroup}>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => run(async () => setVerification(await verifyProviderAccount(id)), "Verification finished.")}
              disabled={busy}
            >
              Verify
            </button>
            <button
              type="button"
              style={styles.secondary}
              onClick={() =>
                run(async () => setCapacity(await refreshProviderAccountCapacity(id)), "Capacity refreshed.")
              }
              disabled={busy}
            >
              Refresh quota
            </button>
          </span>
        }
      >
        <table style={styles.table}>
          <tbody>
            <tr>
              <td style={styles.td}>External ref</td>
              <td style={styles.td}>{account.external_account_ref}</td>
            </tr>
            <tr>
              <td style={styles.td}>Eligibility verified</td>
              <td style={styles.td}>{formatDateTime(account.eligibility_verified_at)}</td>
            </tr>
            <tr>
              <td style={styles.td}>Quota refreshed</td>
              <td style={styles.td}>{formatDateTime(account.quota_refreshed_at)}</td>
            </tr>
            <tr>
              <td style={styles.td}>Limits</td>
              <td style={styles.td}>
                <pre style={styles.pre}>{JSON.stringify(account.limits, null, 2)}</pre>
              </td>
            </tr>
            <tr>
              <td style={styles.td}>Quota state</td>
              <td style={styles.td}>
                <pre style={styles.pre}>{JSON.stringify(account.quota_state, null, 2)}</pre>
              </td>
            </tr>
          </tbody>
        </table>

        {verification ? (
          <Note tone={verification.verification.valid ? "notice" : "warning"}>
            {verification.verification.valid ? "Eligible" : "Not eligible"} — observed by{" "}
            {verification.verification.observed_by}
            {verification.verification.detail ? ` · ${verification.verification.detail}` : ""}
          </Note>
        ) : null}

        {capacity ? (
          <div style={styles.statGrid}>
            <Stat label="Daily limit" value={capacity.capacity.daily_limit ?? "—"} />
            <Stat label="Daily used" value={capacity.capacity.daily_used ?? "—"} />
            <Stat label="Monthly limit" value={capacity.capacity.monthly_limit ?? "—"} />
            <Stat label="Monthly used" value={capacity.capacity.monthly_used ?? "—"} />
            <Stat label="Rate / second" value={capacity.capacity.rate_per_second ?? "—"} />
            <Stat label="Source" value={capacity.capacity.source} />
          </div>
        ) : null}
      </Card>

      <Card title="Edit account">
        <form onSubmit={handleSave}>
          <div style={styles.row}>
            <Field label="Display name">
              <input
                style={styles.input}
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
            </Field>
            <Field label="Status">
              <select
                style={styles.select}
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                {ACCOUNT_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
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
              />
            </Field>
          </div>
          <button type="submit" style={styles.primary} disabled={busy}>
            Save account
          </button>
        </form>
      </Card>

      <Card title="Credentials" description="Secrets are encrypted at rest and never returned.">
        {account.credentials.length === 0 ? (
          <p style={styles.muted}>No credentials stored.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Label</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Key version</th>
                <th style={styles.th}>Created</th>
                <th style={styles.th}>Rotated</th>
                <th style={styles.th} />
              </tr>
            </thead>
            <tbody>
              {account.credentials.map((credential) => (
                <tr key={credential.id}>
                  <td style={styles.td}>{credential.label || "—"}</td>
                  <td style={styles.td}>
                    <StatusPill label={credential.status} />
                  </td>
                  <td style={styles.td}>{credential.key_version}</td>
                  <td style={styles.td}>{formatDateTime(credential.created_at)}</td>
                  <td style={styles.td}>{formatDateTime(credential.rotated_at)}</td>
                  <td style={styles.td}>
                    <button
                      type="button"
                      style={styles.danger}
                      onClick={() =>
                        run(
                          () => revokeProviderCredential(id, credential.id),
                          "Credential revoked.",
                        )
                      }
                      disabled={busy || credential.status === "revoked"}
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <hr style={styles.divider} />

        <form onSubmit={handleAddCredential}>
          <div style={styles.row}>
            <Field label="Secret">
              <input
                style={styles.input}
                required
                type="password"
                value={secret}
                onChange={(event) => setSecret(event.target.value)}
              />
            </Field>
            <Field label="Label">
              <input
                style={styles.input}
                value={secretLabel}
                onChange={(event) => setSecretLabel(event.target.value)}
              />
            </Field>
            <button type="submit" style={styles.primary} disabled={busy}>
              Add credential
            </button>
          </div>
        </form>
      </Card>
    </main>
  );
}
