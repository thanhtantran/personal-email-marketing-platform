"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ApiError, listTemplates, type TemplateSummary } from "@email-platform/api-client";

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<TemplateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    listTemplates(controller.signal)
      .then(setTemplates)
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to view templates."
            : err instanceof Error
              ? err.message
              : "Could not load templates.",
        );
      });
    return () => controller.abort();
  }, []);

  return (
    <main>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <h1>Templates</h1>
        <Link href="/templates/new">New template</Link>
      </div>

      {error ? <p style={{ color: "#ff8a8a" }}>{error}</p> : null}

      {templates === null && !error ? <p>Loading…</p> : null}

      {templates && templates.length === 0 ? (
        <p>No templates yet. Create one to start designing.</p>
      ) : null}

      {templates && templates.length > 0 ? (
        <ul style={{ listStyle: "none", padding: 0 }}>
          {templates.map((template) => (
            <li
              key={template.id}
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 12,
                padding: "12px 0",
                borderBottom: "1px solid #2a2f3a",
              }}
            >
              <Link href={`/templates/${template.id}`}>{template.name}</Link>
              <span style={{ color: "#9aa4b2", fontSize: 13 }}>
                v{template.version} · {template.status}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
    </main>
  );
}
