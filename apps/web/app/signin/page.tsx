"use client";

/**
 * Sign-in placeholder.
 *
 * Phase 1 development signs the workspace owner in automatically
 * (``DEV_AUTO_LOGIN``), so there is nothing to click here yet. The Google
 * sign-in entry point returns in Phase 2.
 */

import Link from "next/link";
import { Card, PageHeader, styles } from "@/components/ui";

export default function SignInPage() {
  return (
    <main style={{ maxWidth: 520 }}>
      <PageHeader
        title="Sign in"
        description="Phase 1 development signs you in automatically."
      />
      <Card>
        <p style={styles.muted}>
          The API issues an owner session on the first request, so a Google account is not
          required yet. Google sign-in returns in Phase 2.
        </p>
        <p>
          <Link href="/" style={styles.primary}>
            Go to dashboard
          </Link>
        </p>
      </Card>
    </main>
  );
}
