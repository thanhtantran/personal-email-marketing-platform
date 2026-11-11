"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import TemplateEditor from "@/components/TemplateEditor";
import { ApiError, getTemplate, type Template } from "@email-platform/api-client";

export default function EditTemplatePage() {
  const { id } = useParams<{ id: string }>();
  const [template, setTemplate] = useState<Template | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getTemplate(id, controller.signal)
      .then(setTemplate)
      .catch((err: unknown) => {
        if (controller.signal.aborted) {
          return;
        }
        setError(
          err instanceof ApiError && err.status === 401
            ? "Sign in to open this template."
            : err instanceof Error
              ? err.message
              : "Could not load the template.",
        );
      });
    return () => controller.abort();
  }, [id]);

  if (error) {
    return (
      <main>
        <p style={{ color: "#ff8a8a" }}>{error}</p>
        <Link href="/templates">Back to templates</Link>
      </main>
    );
  }

  if (!template) {
    return (
      <main>
        <p>Loading…</p>
      </main>
    );
  }

  return (
    <main style={{ maxWidth: 1440 }}>
      <TemplateEditor templateId={template.id} initial={template} />
    </main>
  );
}
