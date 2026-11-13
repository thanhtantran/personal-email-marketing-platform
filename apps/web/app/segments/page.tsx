"use client";

/**
 * Segment list with an inline definition editor.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  createSegment,
  listSegments,
  listTags,
  type SegmentMatch,
  type SegmentOut,
  type TagOut,
} from "@email-platform/api-client";
import SegmentBuilder, {
  buildDefinition,
  emptyDraft,
  type ConditionDraft,
} from "@/components/SegmentBuilder";
import {
  Card,
  Field,
  Note,
  PageHeader,
  describeError,
  formatDateTime,
  styles,
} from "@/components/ui";

export default function SegmentsPage() {
  const [segments, setSegments] = useState<SegmentOut[] | null>(null);
  const [tags, setTags] = useState<TagOut[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  const [name, setName] = useState("");
  const [match, setMatch] = useState<SegmentMatch>("all");
  const [drafts, setDrafts] = useState<ConditionDraft[]>([emptyDraft()]);

  useEffect(() => {
    const controller = new AbortController();
    listSegments(controller.signal)
      .then(setSegments)
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    listTags(controller.signal)
      .then(setTags)
      .catch(() => undefined);
    return () => controller.abort();
  }, [reloadToken]);

  async function handleCreate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const segment = await createSegment(name, buildDefinition(match, drafts));
      setNotice(`Created segment ${segment.name}.`);
      setName("");
      setMatch("all");
      setDrafts([emptyDraft()]);
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
        title="Segments"
        description="Stored audience definitions, validated and evaluated server-side."
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card title="New segment">
        <form onSubmit={handleCreate}>
          <Field label="Name">
            <input
              style={styles.input}
              required
              value={name}
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <SegmentBuilder
            match={match}
            onMatchChange={setMatch}
            drafts={drafts}
            onDraftsChange={setDrafts}
            tags={tags}
          />
          <p>
            <button type="submit" style={styles.primary} disabled={busy}>
              Create segment
            </button>
          </p>
        </form>
      </Card>

      <Card title="All segments">
        {segments === null ? (
          <p style={styles.muted}>Loading…</p>
        ) : segments.length === 0 ? (
          <p style={styles.muted}>No segments yet.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Match</th>
                <th style={styles.th}>Conditions</th>
                <th style={styles.th}>Version</th>
                <th style={styles.th}>Updated</th>
              </tr>
            </thead>
            <tbody>
              {segments.map((segment) => (
                <tr key={segment.id}>
                  <td style={styles.td}>
                    <Link href={`/segments/${segment.id}`}>{segment.name}</Link>
                  </td>
                  <td style={styles.td}>{segment.definition.match}</td>
                  <td style={styles.td}>{segment.definition.conditions.length}</td>
                  <td style={styles.td}>v{segment.version}</td>
                  <td style={styles.td}>{formatDateTime(segment.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </main>
  );
}
