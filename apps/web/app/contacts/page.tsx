"use client";

/**
 * Audience list: filterable, cursor-paged contacts plus an inline create form.
 */

import { useEffect, useMemo, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  CONSENT_STATUSES,
  CONTACT_STATUSES,
  createContact,
  exportContactsCsv,
  listContacts,
  listTags,
  type ContactPage,
  type TagOut,
} from "@email-platform/api-client";
import {
  Card,
  Field,
  Fieldset,
  Note,
  PageHeader,
  StatusPill,
  describeError,
  formatDateTime,
  parseJsonObject,
  styles,
} from "@/components/ui";

interface AppliedFilters {
  status: string;
  consent: string;
  search: string;
  tagId: string;
}

const EMPTY_FILTERS: AppliedFilters = { status: "", consent: "", search: "", tagId: "" };

export default function ContactsPage() {
  const [tags, setTags] = useState<TagOut[]>([]);
  const [page, setPage] = useState<ContactPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [draftFilters, setDraftFilters] = useState<AppliedFilters>(EMPTY_FILTERS);
  const [filters, setFilters] = useState<AppliedFilters>(EMPTY_FILTERS);
  const [cursor, setCursor] = useState<string | null>(null);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([]);

  const [newEmail, setNewEmail] = useState("");
  const [newAttributes, setNewAttributes] = useState("");
  const [newTagIds, setNewTagIds] = useState<string[]>([]);
  const [createNotice, setCreateNotice] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listTags(controller.signal)
      .then(setTags)
      .catch(() => undefined);
    return () => controller.abort();
  }, [reloadToken]);

  useEffect(() => {
    const controller = new AbortController();
    listContacts(
      {
        limit: 25,
        cursor,
        status: filters.status || undefined,
        consent_status: filters.consent || undefined,
        search: filters.search || undefined,
        tag_id: filters.tagId || undefined,
      },
      controller.signal,
    )
      .then(setPage)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    return () => controller.abort();
  }, [filters, cursor, reloadToken]);

  const tagName = useMemo(() => {
    const lookup = new Map(tags.map((tag) => [tag.id, tag.name]));
    return (id: string) => lookup.get(id) ?? id;
  }, [tags]);

  function applyFilters() {
    setFilters(draftFilters);
    setCursor(null);
    setCursorHistory([]);
    setError(null);
  }

  function goNext() {
    if (!page?.next_cursor) {
      return;
    }
    setCursorHistory((history) => [...history, cursor]);
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
    setCreateNotice(null);
    try {
      const contact = await createContact({
        email: newEmail,
        attributes: parseJsonObject(newAttributes),
        tag_ids: newTagIds,
      });
      setCreateNotice(`Created ${contact.email_display}.`);
      setNewEmail("");
      setNewAttributes("");
      setNewTagIds([]);
      setCursor(null);
      setCursorHistory([]);
      setReloadToken((token) => token + 1);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleExport() {
    setBusy(true);
    setError(null);
    try {
      const blob = await exportContactsCsv();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "contacts.csv";
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <PageHeader
        title="Audience"
        description="Contacts, consent state and tags for this workspace."
        actions={
          <button type="button" style={styles.secondary} onClick={handleExport} disabled={busy}>
            Export CSV
          </button>
        }
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {createNotice ? <Note tone="notice">{createNotice}</Note> : null}

      <Card title="Filters">
        <div style={styles.row}>
          <Field label="Search">
            <input
              style={styles.input}
              value={draftFilters.search}
              onChange={(event) =>
                setDraftFilters({ ...draftFilters, search: event.target.value })
              }
              placeholder="email"
            />
          </Field>
          <Field label="Status">
            <select
              style={styles.select}
              value={draftFilters.status}
              onChange={(event) =>
                setDraftFilters({ ...draftFilters, status: event.target.value })
              }
            >
              <option value="">any</option>
              {CONTACT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Consent">
            <select
              style={styles.select}
              value={draftFilters.consent}
              onChange={(event) =>
                setDraftFilters({ ...draftFilters, consent: event.target.value })
              }
            >
              <option value="">any</option>
              {CONSENT_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Tag">
            <select
              style={styles.select}
              value={draftFilters.tagId}
              onChange={(event) =>
                setDraftFilters({ ...draftFilters, tagId: event.target.value })
              }
            >
              <option value="">any</option>
              {tags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
            </select>
          </Field>
          <button type="button" style={styles.primary} onClick={applyFilters}>
            Apply
          </button>
          <button
            type="button"
            style={styles.secondary}
            onClick={() => {
              setDraftFilters(EMPTY_FILTERS);
              setFilters(EMPTY_FILTERS);
              setCursor(null);
              setCursorHistory([]);
            }}
          >
            Reset
          </button>
        </div>
      </Card>

      <Card title="Create contact">
        <form onSubmit={handleCreate}>
          <Field label="Email">
            <input
              style={styles.input}
              type="email"
              required
              value={newEmail}
              onChange={(event) => setNewEmail(event.target.value)}
            />
          </Field>
          <Field label="Attributes (JSON object)" hint="Optional. Addressable as attribute.<key>.">
            <textarea
              style={styles.textarea}
              value={newAttributes}
              onChange={(event) => setNewAttributes(event.target.value)}
              placeholder='{"first_name": "Ada"}'
            />
          </Field>
          {tags.length > 0 ? (
            <Fieldset label="Tags">
              <span style={styles.chips}>
                {tags.map((tag) => (
                  <label key={tag.id} style={styles.checkbox}>
                    <input
                      type="checkbox"
                      checked={newTagIds.includes(tag.id)}
                      onChange={(event) =>
                        setNewTagIds((current) =>
                          event.target.checked
                            ? [...current, tag.id]
                            : current.filter((id) => id !== tag.id),
                        )
                      }
                    />
                    {tag.name}
                  </label>
                ))}
              </span>
            </Fieldset>
          ) : null}
          <button type="submit" style={styles.primary} disabled={busy}>
            Create contact
          </button>
        </form>
      </Card>

      <Card
        title={page ? `Contacts (${page.total})` : "Contacts"}
        actions={
          <span style={styles.inlineGroup}>
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
          <p style={styles.muted}>No contacts match these filters.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Email</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Consent</th>
                <th style={styles.th}>Tags</th>
                <th style={styles.th}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((contact) => (
                <tr key={contact.id}>
                  <td style={styles.td}>
                    <Link href={`/contacts/${contact.id}`}>{contact.email_display}</Link>
                  </td>
                  <td style={styles.td}>
                    <StatusPill label={contact.status} />
                  </td>
                  <td style={styles.td}>{contact.consent_status}</td>
                  <td style={styles.td}>
                    {contact.tags.length === 0 ? (
                      <span style={styles.muted}>—</span>
                    ) : (
                      <span style={styles.chips}>
                        {contact.tags.map((tag) => (
                          <span key={tag.id} style={styles.chip}>
                            {tagName(tag.id)}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                  <td style={styles.td}>{formatDateTime(contact.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}
