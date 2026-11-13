"use client";

/**
 * CSV import wizard.
 *
 * The flow is staged: declare the column mapping, PUT the CSV to a short-lived
 * presigned URL (no session cookie, the signature would break), preview the
 * planned outcomes, then commit with a merge policy.
 */

import { useState, type FormEvent } from "react";
import {
  MERGE_POLICIES,
  commitImport,
  createImport,
  previewImport,
  uploadImportFile,
  type ImportCreated,
  type ImportMapping,
  type ImportOut,
  type ImportPreview,
  type MergePolicy,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Fieldset,
  Note,
  PageHeader,
  Stat,
  describeError,
  styles,
} from "@/components/ui";

interface AttributeRow {
  key: string;
  column: string;
}

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `import-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export default function ImportsPage() {
  const [emailColumn, setEmailColumn] = useState("email");
  const [consentStatusColumn, setConsentStatusColumn] = useState("");
  const [consentAtColumn, setConsentAtColumn] = useState("");
  const [consentSourceColumn, setConsentSourceColumn] = useState("");
  const [consentEvidenceColumn, setConsentEvidenceColumn] = useState("");
  const [attributeRows, setAttributeRows] = useState<AttributeRow[]>([]);

  const [created, setCreated] = useState<ImportCreated | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [uploaded, setUploaded] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [mergePolicy, setMergePolicy] = useState<MergePolicy>("skip");
  const [committed, setCommitted] = useState<ImportOut | null>(null);

  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  function buildMapping(): ImportMapping {
    const attributes: Record<string, string> = {};
    for (const row of attributeRows) {
      const key = row.key.trim();
      const column = row.column.trim();
      if (key && column) {
        attributes[key] = column;
      }
    }
    const mapping: ImportMapping = { email: emailColumn.trim(), attributes };
    if (consentStatusColumn.trim()) {
      mapping.consent_status = consentStatusColumn.trim();
    }
    if (consentAtColumn.trim()) {
      mapping.consent_at = consentAtColumn.trim();
    }
    if (consentSourceColumn.trim()) {
      mapping.consent_source = consentSourceColumn.trim();
    }
    if (consentEvidenceColumn.trim()) {
      mapping.consent_evidence_ref = consentEvidenceColumn.trim();
    }
    return mapping;
  }

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    setPreview(null);
    setCommitted(null);
    setUploaded(false);
    try {
      const result = await createImport(buildMapping(), newIdempotencyKey());
      setCreated(result);
      setNotice(
        `Import ${result.import_id} created. Upload the CSV within ${result.upload_expires_seconds}s.`,
      );
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleUpload() {
    if (!created || !file) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await uploadImportFile(created.upload_url, file);
      setUploaded(true);
      setNotice("CSV uploaded. Preview the planned outcomes next.");
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handlePreview() {
    if (!created) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setPreview(await previewImport(created.import_id));
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCommit() {
    if (!created) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await commitImport(created.import_id, mergePolicy);
      setCommitted(result);
      setNotice(`Import ${result.id} is ${result.status}.`);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <PageHeader
        title="Imports"
        description="Stage a CSV, review the row plan, then apply it with an explicit merge policy."
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card title="1 · Column mapping">
        <form onSubmit={handleCreate}>
          <div style={styles.row}>
            <Field label="Email column" hint="Required">
              <input
                style={styles.input}
                required
                value={emailColumn}
                onChange={(event) => setEmailColumn(event.target.value)}
              />
            </Field>
            <Field label="Consent status column">
              <input
                style={styles.input}
                value={consentStatusColumn}
                onChange={(event) => setConsentStatusColumn(event.target.value)}
              />
            </Field>
            <Field label="Consent at column">
              <input
                style={styles.input}
                value={consentAtColumn}
                onChange={(event) => setConsentAtColumn(event.target.value)}
              />
            </Field>
          </div>
          <div style={styles.row}>
            <Field label="Consent source column">
              <input
                style={styles.input}
                value={consentSourceColumn}
                onChange={(event) => setConsentSourceColumn(event.target.value)}
              />
            </Field>
            <Field label="Consent evidence ref column">
              <input
                style={styles.input}
                value={consentEvidenceColumn}
                onChange={(event) => setConsentEvidenceColumn(event.target.value)}
              />
            </Field>
          </div>

          <Fieldset label="Attribute mappings" hint="Attribute key → CSV column name.">
            <span>
              {attributeRows.map((row, index) => (
                <span key={index} style={{ ...styles.row, marginBottom: 6 }}>
                  <input
                    style={styles.input}
                    placeholder="first_name"
                    value={row.key}
                    onChange={(event) =>
                      setAttributeRows(
                        attributeRows.map((current, position) =>
                          position === index ? { ...current, key: event.target.value } : current,
                        ),
                      )
                    }
                  />
                  <input
                    style={styles.input}
                    placeholder="First Name"
                    value={row.column}
                    onChange={(event) =>
                      setAttributeRows(
                        attributeRows.map((current, position) =>
                          position === index ? { ...current, column: event.target.value } : current,
                        ),
                      )
                    }
                  />
                  <button
                    type="button"
                    style={styles.danger}
                    onClick={() =>
                      setAttributeRows(attributeRows.filter((_, position) => position !== index))
                    }
                  >
                    Remove
                  </button>
                </span>
              ))}
            </span>
          </Field>
          <span style={styles.inlineGroup}>
            <button
              type="button"
              style={styles.secondary}
              onClick={() => setAttributeRows([...attributeRows, { key: "", column: "" }])}
            >
              Add attribute
            </button>
            <button type="submit" style={styles.primary} disabled={busy}>
              Create import
            </button>
          </span>
        </form>
      </Card>

      {created ? (
        <Card
          title="2 · Upload CSV"
          description={`Staged object expires after ${created.upload_expires_seconds} seconds.`}
          actions={uploaded ? <Note tone="notice">Uploaded</Note> : null}
        >
          <p style={styles.muted}>
            Presigned URL: <span style={styles.mono}>{created.upload_url}</span>
          </p>
          <div style={styles.row}>
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setUploaded(false);
                setPreview(null);
              }}
            />
            <button
              type="button"
              style={styles.primary}
              onClick={handleUpload}
              disabled={busy || !file}
            >
              Upload
            </button>
          </div>
        </Card>
      ) : null}

      {created ? (
        <Card
          title="3 · Preview"
          actions={
            <button
              type="button"
              style={styles.secondary}
              onClick={handlePreview}
              disabled={busy || !uploaded}
            >
              Preview
            </button>
          }
        >
          {preview === null ? (
            <p style={styles.muted}>
              {uploaded
                ? "Run a preview to see the planned outcomes before committing."
                : "Upload the CSV first."}
            </p>
          ) : (
            <>
              <div style={styles.statGrid}>
                {Object.entries(preview.counts).map(([key, value]) => (
                  <Stat key={key} label={key} value={value} />
                ))}
              </div>
              {preview.truncated ? (
                <Note tone="warning">
                  The file is large; counts cover a truncated read of the staged object.
                </Note>
              ) : null}
              {preview.errors.length > 0 ? (
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Row</th>
                      <th style={styles.th}>Outcome</th>
                      <th style={styles.th}>Error</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.errors.map((row) => (
                      <tr key={row.row_number}>
                        <td style={styles.td}>{row.row_number}</td>
                        <td style={styles.td}>{row.outcome}</td>
                        <td style={styles.td}>{row.error_code ?? "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p style={styles.muted}>No row errors were found.</p>
              )}
              {preview.errors_truncated ? (
                <Note tone="warning">Only the first 200 errors are shown.</Note>
              ) : null}
            </>
          )}
        </Card>
      ) : null}

      {created ? (
        <Card title="4 · Commit">
          <div style={styles.row}>
            <Field label="Merge policy">
              <select
                style={styles.select}
                value={mergePolicy}
                onChange={(event) => setMergePolicy(event.target.value as MergePolicy)}
              >
                {MERGE_POLICIES.map((policy) => (
                  <option key={policy} value={policy}>
                    {policy}
                  </option>
                ))}
              </select>
            </Field>
            <button
              type="button"
              style={styles.primary}
              onClick={handleCommit}
              disabled={busy || preview === null}
            >
              Commit import
            </button>
          </div>
          <p style={styles.hint}>
            Commit is replay-safe: repeating it returns the stored result instead of applying rows
            twice.
          </p>
          {committed ? (
            <>
              <div style={styles.statGrid}>
                {Object.entries(committed.counts ?? {}).map(([key, value]) => (
                  <Stat key={key} label={key} value={String(value)} />
                ))}
              </div>
              <pre style={styles.pre}>{JSON.stringify(committed, null, 2)}</pre>
            </>
          ) : null}
        </Card>
      ) : null}
    </main>
  );
}
