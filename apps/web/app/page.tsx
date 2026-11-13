"use client";

/**
 * Operator landing page.
 *
 * Resolves the current session and a few headline numbers. A missing session is
 * not an error state: it renders the sign-in call to action instead.
 */

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  ApiError,
  getMe,
  getRoutingStatus,
  listCampaigns,
  listContacts,
  type CampaignSummary,
  type MeOut,
  type RoutingStatus,
} from "@email-platform/api-client";
import {
  Card,
  Note,
  PageHeader,
  Stat,
  StatusPill,
  describeError,
  formatDateTime,
  styles,
} from "@/components/ui";

export default function DashboardPage() {
  const [me, setMe] = useState<MeOut | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [campaignTotal, setCampaignTotal] = useState<number | null>(null);
  const [contactTotal, setContactTotal] = useState<number | null>(null);
  const [routing, setRouting] = useState<RoutingStatus | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getMe(controller.signal)
      .then(setMe)
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
          setSignedOut(true);
          return;
        }
        setError(describeError(err));
      });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!me) {
      return;
    }
    const controller = new AbortController();
    listCampaigns({ limit: 5 }, controller.signal)
      .then((page) => {
        setCampaigns(page.items);
        setCampaignTotal(page.total);
      })
      .catch(() => undefined);
    listContacts({ limit: 1 }, controller.signal)
      .then((page) => setContactTotal(page.total))
      .catch(() => undefined);
    getRoutingStatus(controller.signal)
      .then(setRouting)
      .catch(() => undefined);
    return () => controller.abort();
  }, [me]);

  if (signedOut) {
    return (
      <main>
        <PageHeader
          title="Dashboard"
          description="Sign in to load your workspace, audience and campaign state."
        />
        <Card>
          <p style={styles.muted}>No active session was found for this browser.</p>
          <p>
            <Link href="/signin">Go to sign in</Link>
          </p>
        </Card>
      </main>
    );
  }

  if (error) {
    return (
      <main>
        <PageHeader title="Dashboard" />
        <Note tone="error">{error}</Note>
      </main>
    );
  }

  if (!me) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main>
      <PageHeader
        title={`Welcome, ${me.user.display_name || me.user.email}`}
        description={
          <>
            Workspace <strong>{me.workspace.name}</strong> ({me.workspace.slug}) · role {me.role}
          </>
        }
        actions={<Link href="/campaigns">Campaigns</Link>}
      />

      <div style={styles.statGrid}>
        <Stat label="Contacts" value={contactTotal ?? "—"} />
        <Stat label="Campaigns" value={campaignTotal ?? "—"} />
        <Stat
          label="Marketing routing"
          value={routing ? (routing.marketing_paused ? "Paused" : routing.marketing_eligible ? "Routing" : "Blocked") : "—"}
          hint={routing?.paused_reason ?? undefined}
        />
        <Stat
          label="Capacity"
          value={routing ? (routing.capacity_fresh ? "Fresh" : "Stale") : "—"}
          hint={routing ? `${routing.exclusions.length} exclusion(s)` : undefined}
        />
      </div>

      <Card title="Recent campaigns" actions={<Link href="/campaigns">View all</Link>}>
        {campaigns.length === 0 ? (
          <p style={styles.muted}>No campaigns yet.</p>
        ) : (
          <table style={styles.table}>
            <thead>
              <tr>
                <th style={styles.th}>Name</th>
                <th style={styles.th}>Status</th>
                <th style={styles.th}>Scheduled</th>
                <th style={styles.th}>Launched</th>
              </tr>
            </thead>
            <tbody>
              {campaigns.map((campaign) => (
                <tr key={campaign.id}>
                  <td style={styles.td}>
                    <Link href={`/campaigns/${campaign.id}`}>{campaign.name}</Link>
                  </td>
                  <td style={styles.td}>
                    <StatusPill label={campaign.status} />
                  </td>
                  <td style={styles.td}>{formatDateTime(campaign.scheduled_at)}</td>
                  <td style={styles.td}>{formatDateTime(campaign.launched_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <Card title="Workspace identity">
        <table style={styles.table}>
          <tbody>
            <tr>
              <td style={styles.td}>User</td>
              <td style={styles.td}>{me.user.email}</td>
            </tr>
            <tr>
              <td style={styles.td}>User status</td>
              <td style={styles.td}>{me.user.status}</td>
            </tr>
            <tr>
              <td style={styles.td}>Workspace status</td>
              <td style={styles.td}>{me.workspace.status}</td>
            </tr>
            <tr>
              <td style={styles.td}>CSRF cookie</td>
              <td style={styles.td}>{me.csrf_token_present ? "present" : "missing"}</td>
            </tr>
          </tbody>
        </table>
        {me.csrf_token_present ? null : (
          <Note tone="warning">
            The CSRF cookie is missing, so mutations will be rejected. Reload the page after
            signing in.
          </Note>
        )}
      </Card>
    </main>
  );
}
