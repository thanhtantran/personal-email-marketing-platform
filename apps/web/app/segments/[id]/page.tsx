"use client";

/**
 * Segment detail: edit the definition and estimate its reach.
 */

import { useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  estimateSegment,
  getSegment,
  listTags,
  updateSegment,
  type SegmentEstimate,
  type SegmentMatch,
  type SegmentOut,
  type TagOut,
} from "@email-platform/api-client";
import SegmentBuilder, {
  buildDefinition,
  toDrafts,
  type ConditionDraft,
} from "@/components/SegmentBuilder";
import {
  Card,
  Field,
  Note,
  PageHeader,
  Stat,
  describeError,
  styles,
} from "@/components/ui";

export default function SegmentDetailPage() {
  const { id } = useParams<{ id: string }>();

  const [segment, setSegment] = useState<SegmentOut | null>(null);
  const [tags, setTags] = useState<TagOut[]>([]);
  const [estimate, setEstimate] = useState<SegmentEstimate | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const [name, setName] = useState("");
  const [match, setMatch] = useState<SegmentMatch>("all");
  const [drafts, setDrafts] = useState<ConditionDraft[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    getSegment(id, controller.signal)
      .then((loaded) => {
        setSegment(loaded);
        setName(loaded.name);
        setMatch(loaded.definition.match);
        setDrafts(toDrafts(loaded.definition));
      })
      .catch((err: unknown) => {
        if (!controller.signal.aborted) {
          setError(describeError(err));
        }
      });
    listTags(controller.signal)
      .then(setTags)
      .catch(() => undefined);
    return () => controller.abort();
  }, [id]);

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await updateSegment(id, name, buildDefinition(match, drafts));
      setSegment(updated);
      setNotice(`Saved (version ${updated.version}).`);
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleEstimate() {
    setBusy(true);
    setError(null);
    try {
      setEstimate(await estimateSegment(id));
    } catch (err: unknown) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }

  if (error && !segment) {
    return (
      <main>
        <Note tone="error">{error}</Note>
        <Link href="/segments">Back to segments</Link>
      </main>
    );
  }

  if (!segment) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main>
      <PageHeader
        title={segment.name}
        description={`Version ${segment.version} · ${segment.definition.conditions.length} condition(s)`}
        actions={<Link href="/segments">Back to segments</Link>}
      />

      {error ? <Note tone="error">{error}</Note> : null}
      {notice ? <Note tone="notice">{notice}</Note> : null}

      <Card title="Reach">
        <span style={styles.inlineGroup}>
          <button type="button" style={styles.secondary} onClick={handleEstimate} disabled={busy}>
            Estimate audience
          </button>
        </span>
        {estimate ? (
          <div style={styles.statGrid}>
            <Stat label="Matches" value={estimate.match_count} />
            <Stat
              label="Eligible"
              value={estimate.eligible_count}
              hint="Matches minus suppressed or unsubscribed"
            />
          </div>
        ) : (
          <p style={styles.muted}>Run an estimate to see how many contacts match.</p>
        )}
      </Card>

      <Card title="Definition">
        <form onSubmit={handleSave}>
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
              Save definition
            </button>
          </p>
        </form>
      </Card>

      <Card title="Stored definition (JSON)">
        <pre style={styles.pre}>{JSON.stringify(segment.definition, null, 2)}</pre>
      </Card>
    </main>
  );
}
