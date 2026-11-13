"use client";

/**
 * Contact detail: consent/status editing, tag membership and suppression.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import {
  CONSENT_STATUSES,
  CONTACT_STATUSES,
  SUPPRESSION_REASONS,
  attachTag,
  createTag,
  deleteContact,
  detachTag,
  getContact,
  listTags,
  suppressContact,
  updateContact,
  type ContactOut,
  type SuppressionOut,
  type TagOut,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Note,
  PageHeader,
  StatusPill,
  describeError,
  formatDateTime,
  fromDateTimeLocal,
  parseJsonObject,
  styles,
  toDateTimeLocal,
} from "@/components/ui";

export default function ContactDetailPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  const [contact, setContact] = useState<ContactOut | null>(null);
  const [tags, setTags] = useState<TagOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [status, setStatus] = useState("active");
  const [consentStatus, setConsentStatus] = useState("unknown");
  const [consentSource, setConsentSource] = useState("");
  const [consentEvidence, setConsentEvidence] = useState("");
  const [consentAt, setConsentAt] = useState("");
  const [attributesText, setAttributesText] = useState("");

  const [tagToAttach, setTagToAttach] = useState("");
  const [newTagName, setNewTagName] = useState("");

  const [suppression, setSuppression] = useState<SuppressionOut | null>(null);
  const [reason, setReason] = useState<string>(SUPPRESSION_REASONS[0]);
  const [suppressionSource, setSuppressionSource] = useState("");
  const [suppressionOccurredAt, setSuppressionOccurredAt] = useState("");
  const [suppressionEvidence, setSuppressionEvidence] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    getContact(id, controller.signal)
      .then(setContact)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    return () => controller.abort();
  }, [id, reloadToken]);

  useEffect(() => {
    const controller = new AbortController();
    listTags(controller.signal)
      .then(setTags)
      .catch(() => undefined);
    return () => controller.abort();
  }, [reloadToken]);

  useEffect(() => {
    if (!contact) {
      return;
    }
    setStatus(contact.status);
    setConsentStatus(contact.consent_status);
    setConsentSource(contact.consent_source ?? "");
    setConsentEvidence(contact.consent_evidence_ref ?? "");
    setConsentAt(toDateTimeLocal(contact.consent_at));
    setAttributesText(
      Object.keys(contact.attributes).length ? JSON.stringify(contact.attributes, null, 2) : "",
    );
  }, [contact]);

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateContact(id, {
        status,
        consent_status: consentStatus,
        consent_source: consentSource || null,
        consent_evidence_ref: consentEvidence || null,
        consent_at: fromDateTimeLocal(consentAt),
        attributes: parseJsonObject(attributesText),
      });
      setContact(updated);
      setNotice("Contact updated.");
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleAttach() {
    if (!tagToAttach) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await attachTag(id, tagToAttach);
      setTagToAttach("");
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDetach(tagId: string) {
    setBusy(true);
    setError(null);
    try {
      await detachTag(id, tagId);
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCreateTag(event: FormEvent) {
    event.preventDefault();
    if (!newTagName.trim()) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createTag(newTagName.trim());
      setNewTagName("");
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleSuppress(event: FormEvent) {
    event.preventDefault();
    if (!contact) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await suppressContact(id, {
        email: contact.normalized_email,
        reason,
        source: suppressionSource || null,
        occurred_at: fromDateTimeLocal(suppressionOccurredAt),
        evidence: suppressionEvidence.trim() ? parseJsonObject(suppressionEvidence) : null,
      });
      setSuppression(result);
      setNotice(`Suppression recorded (${result.reason}).`);
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!window.confirm("Delete this contact? This cannot be undone.")) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await deleteContact(id);
      router.push("/contacts");
    } catch (err: unknown) {
      setError(describeError(err));
      setBusy(false);
    }
  }

  if (error && !contact) {
    return (
      <main>
        <Note tone="error">{error}</Note>
        <Link href="/contacts">Back to audience</Link>
      </main>
    );
  }

  if (!contact) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  const attachedIds = new Set(contact.tags.map((tag) => tag.id));
  const availableTags = tags.filter((tag) => !attachedIds.has(tag.id));

  return (
    <main>
      <PageHeader
        title={contact.email_display}
        description={
          <>
            <StatusPill label={contact.status} /> consent {contact.consent_status}
          </>
        }
        actions={<Link href="/contacts">Back to audience</Link>}
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card title="Profile">
        <table style={styles.table}>
          <tbody>
            <tr>
              <td style={styles.td}>Normalized email</td>
              <td style={styles.td}>{contact.normalized_email}</td>
            </tr>
            <tr>
              <td style={styles.td}>Created</td>
              <td style={styles.td}>{formatDateTime(contact.created_at)}</td>
            </tr>
            <tr>
              <td style={styles.td}>Updated</td>
              <td style={styles.td}>{formatDateTime(contact.updated_at)}</td>
            </tr>
            <tr>
              <td style={styles.td}>Consent recorded</td>
              <td style={styles.td}>{formatDateTime(contact.consent_at)}</td>
            </tr>
            <tr>
              <td style={styles.td}>Contact id</td>
              <td style={{ ...styles.td, ...styles.mono }}>{contact.id}</td>
            </tr>
          </tbody>
        </table>
      </Card>

      <Card title="Edit state">
        <form onSubmit={handleSave}>
          <div style={styles.row}>
            <Field label="Status">
              <select
                style={styles.select}
                value={status}
                onChange={(event) => setStatus(event.target.value)}
              >
                {CONTACT_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Consent status">
              <select
                style={styles.select}
                value={consentStatus}
                onChange={(event) => setConsentStatus(event.target.value)}
              >
                {CONSENT_STATUSES.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Consent at">
              <input
                style={styles.input}
                type="datetime-local"
                value={consentAt}
                onChange={(event) => setConsentAt(event.target.value)}
              />
            </Field>
          </div>
          <div style={styles.row}>
            <Field label="Consent source">
              <input
                style={styles.input}
                value={consentSource}
                onChange={(event) => setConsentSource(event.target.value)}
              />
            </Field>
            <Field label="Consent evidence ref">
              <input
                style={styles.input}
                value={consentEvidence}
                onChange={(event) => setConsentEvidence(event.target.value)}
              />
            </Field>
          </div>
          <Field label="Attributes (JSON object)">
            <textarea
              style={styles.textarea}
              value={attributesText}
              onChange={(event) => setAttributesText(event.target.value)}
            />
          </Field>
          <span style={styles.inlineGroup}>
            <button type="submit" style={styles.primary} disabled={busy}>
              Save changes
            </button>
            <button type="button" style={styles.danger} onClick={handleDelete} disabled={busy}>
              Delete contact
            </button>
          </span>
        </form>
      </Card>

      <Card title="Tags">
        <span style={styles.chips}>
          {contact.tags.length === 0 ? (
            <span style={styles.muted}>No tags attached.</span>
          ) : (
            contact.tags.map((tag) => (
              <span key={tag.id} style={styles.chip}>
                {tag.name}
                <button
                  type="button"
                  style={{ ...styles.link, marginLeft: 6 }}
                  onClick={() => handleDetach(tag.id)}
                  disabled={busy}
                >
                  remove
                </button>
              </span>
            ))
          )}
        </span>

        <hr style={styles.divider} />

        <div style={styles.row}>
          <Field label="Attach existing tag">
            <select
              style={styles.select}
              value={tagToAttach}
              onChange={(event) => setTagToAttach(event.target.value)}
            >
              <option value="">select a tag</option>
              {availableTags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
            </select>
          </Field>
          <button
            type="button"
            style={styles.secondary}
            onClick={handleAttach}
            disabled={busy || !tagToAttach}
          >
            Attach
          </button>
        </div>

        <form onSubmit={handleCreateTag} style={styles.row}>
          <Field label="Create new tag">
            <input
              style={styles.input}
              value={newTagName}
              onChange={(event) => setNewTagName(event.target.value)}
              placeholder="vip"
            />
          </Field>
          <button type="submit" style={styles.secondary} disabled={busy || !newTagName.trim()}>
            Create tag
          </button>
        </form>
      </Card>

      <Card
        title="Suppress"
        description="Suppression mirrors into an unrecoverable status for unsubscribe, complaint and hard bounce."
      >
        <form onSubmit={handleSuppress}>
          <div style={styles.row}>
            <Field label="Reason">
              <select
                style={styles.select}
                value={reason}
                onChange={(event) => setReason(event.target.value)}
              >
                {SUPPRESSION_REASONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Source">
              <input
                style={styles.input}
                value={suppressionSource}
                onChange={(event) => setSuppressionSource(event.target.value)}
                placeholder="manual"
              />
            </Field>
            <Field label="Occurred at">
              <input
                style={styles.input}
                type="datetime-local"
                value={suppressionOccurredAt}
                onChange={(event) => setSuppressionOccurredAt(event.target.value)}
              />
            </Field>
          </div>
          <Field label="Evidence (JSON object)">
            <textarea
              style={styles.textarea}
              value={suppressionEvidence}
              onChange={(event) => setSuppressionEvidence(event.target.value)}
            />
          </Field>
          <button type="submit" style={styles.primary} disabled={busy}>
            Record suppression
          </button>
        </form>

        {suppression ? (
          <pre style={styles.pre}>{JSON.stringify(suppression, null, 2)}</pre>
        ) : null}
      </Card>
    </main>
  );
}
