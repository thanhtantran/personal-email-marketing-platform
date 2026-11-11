"use client";

import TemplateEditor from "@/components/TemplateEditor";

export default function NewTemplatePage() {
  return (
    <main style={{ maxWidth: 1440 }}>
      <h1>New template</h1>
      <p style={{ color: "#9aa4b2" }}>
        Design the email, then save it. The server renders and sanitizes the exported MJML.
      </p>
      <TemplateEditor />
    </main>
  );
}
