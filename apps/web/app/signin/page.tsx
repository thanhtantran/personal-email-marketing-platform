"use client";

/**
 * Google sign-in entry point.
 *
 * The start endpoint is a top-level navigation rather than a fetch: Google
 * redirects back to the API callback, which sets the session cookie and sends
 * the browser back into the app. A fetch would be blocked cross-origin.
 */

import { GOOGLE_SIGN_IN_URL } from "@email-platform/api-client";
import { Card, PageHeader, styles } from "@/components/ui";

export default function SignInPage() {
  return (
    <main style={{ maxWidth: 520 }}>
      <PageHeader
        title="Sign in"
        description="Authenticate with your Google account to open the workspace."
      />
      <Card>
        <p style={styles.muted}>
          You will be redirected to Google and then back here once the session cookie is set.
        </p>
        <p>
          <a href={GOOGLE_SIGN_IN_URL} style={styles.primary}>
            Sign in with Google
          </a>
        </p>
      </Card>
    </main>
  );
}
