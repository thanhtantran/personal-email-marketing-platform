"use client";

/**
 * GrapesJS + MJML template editor.
 *
 * The editor state (GrapesJS project data) is what the operator reopens; the
 * authoritative source is the exported MJML, which the API renders, sanitizes
 * and derives the plaintext alternative from. Preview and test sends therefore
 * always show server-rendered output, not the editor canvas.
 */

import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Editor } from "grapesjs";
import "grapesjs/dist/css/grapes.min.css";
import {
  ApiError,
  PERSONALIZATION_VARIABLES,
  SUPPORTED_MJML_COMPONENTS,
  createTemplate,
  renderTemplate,
  testSendTemplate,
  updateTemplate,
  type Template,
  type TemplateRenderResult,
  type TemplateStatus,
} from "@email-platform/api-client";

/** GrapesJS project data, as accepted by ``loadProjectData``. */
type ProjectDataArg = Parameters<Editor["loadProjectData"]>[0];

const TEMPLATE_STATUSES: TemplateStatus[] = ["draft", "published", "archived"];

const DEVICES = [
  { id: "mobile", label: "Mobile", width: 375 },
  { id: "tablet", label: "Tablet", width: 768 },
  { id: "desktop", label: "Desktop", width: 0 },
] as const;

type DeviceId = (typeof DEVICES)[number]["id"];

interface TemplateEditorProps {
  templateId?: string;
  initial?: Template;
}

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    const reason = error.body.reason;
    return typeof reason === "string" ? `${error.message} (${reason})` : error.message;
  }
  return error instanceof Error ? error.message : "Unexpected error";
}

export default function TemplateEditor({ templateId, initial }: TemplateEditorProps) {
  const router = useRouter();
  const containerRef = useRef<HTMLDivElement | null>(null);
  const editorRef = useRef<Editor | null>(null);
  const initialRef = useRef(initial);

  const [name, setName] = useState(initial?.name ?? "Untitled template");
  const [status, setStatus] = useState<TemplateStatus>(initial?.status ?? "draft");
  const [version, setVersion] = useState<number>(initial?.version ?? 1);
  const [values, setValues] = useState<Record<string, string>>({});
  const [device, setDevice] = useState<DeviceId>("desktop");
  const [preview, setPreview] = useState<TemplateRenderResult | null>(null);
  const [recipient, setRecipient] = useState("");
  const [subject, setSubject] = useState("");
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }
    let cancelled = false;
    let editor: Editor | null = null;

    void (async () => {
      const [{ default: grapesjs }, { default: grapesjsMjml }] = await Promise.all([
        import("grapesjs"),
        import("grapesjs-mjml"),
      ]);
      if (cancelled) {
        return;
      }
      editor = grapesjs.init({
        container,
        height: "100%",
        // The API owns persistence; the editor must not restore another
        // template from shared local storage.
        storageManager: { autosave: false, autoload: false },
        plugins: [grapesjsMjml],
        pluginsOpts: { "grapesjs-mjml": {} },
      });
      editorRef.current = editor;

      const snapshot = initialRef.current;
      if (snapshot) {
        const data = snapshot.editor_json ?? {};
        if (Object.keys(data).length > 0) {
          editor.loadProjectData(data as unknown as ProjectDataArg);
        } else if (snapshot.mjml_source) {
          editor.setComponents(snapshot.mjml_source);
        }
      }
      editor.on("update", () => setDirty(true));
    })();

    return () => {
      cancelled = true;
      editor?.destroy();
      editorRef.current = null;
    };
  }, []);

  const handleSave = useCallback(async () => {
    const editor = editorRef.current;
    if (!editor) {
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const payload = {
        name: name.trim() || "Untitled template",
        mjml_source: editor.getHtml(),
        editor_json: editor.getProjectData() as unknown as Record<string, unknown>,
        status,
      };
      if (templateId) {
        const updated = await updateTemplate(templateId, payload);
        setVersion(updated.version);
        setDirty(false);
        setNotice(`Saved as version ${updated.version}.`);
      } else {
        const created = await createTemplate(payload);
        setDirty(false);
        setNotice("Template created.");
        router.replace(`/templates/${created.id}`);
      }
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [name, router, status, templateId]);

  const handlePreview = useCallback(async () => {
    if (!templateId || dirty) {
      setError("Save the template before previewing.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      setPreview(await renderTemplate(templateId, { values }));
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [dirty, templateId, values]);

  const handleTestSend = useCallback(async () => {
    if (!templateId || dirty) {
      setError("Save the template before sending a test.");
      return;
    }
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const result = await testSendTemplate(templateId, { recipient, subject, values });
      setPreview({
        template_id: result.template_id,
        version: result.version,
        html: result.html,
        text: result.text,
        missing: result.missing,
        used_fallback: result.used_fallback,
      });
      setNotice(
        `Test message handed to the ${result.provider} sender; it was not enqueued for delivery.`,
      );
    } catch (err) {
      setError(describeError(err));
    } finally {
      setBusy(false);
    }
  }, [dirty, recipient, subject, templateId, values]);

  const frameWidth = DEVICES.find((entry) => entry.id === device)?.width ?? 0;
  const canPreview = Boolean(templateId) && !dirty;

  return (
    <div style={{ maxWidth: 1440 }}>
      <header style={styles.header}>
        <div style={styles.headerRow}>
          <Link href="/templates">← Templates</Link>
          <input
            aria-label="Template name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            style={styles.nameInput}
          />
          <select
            aria-label="Template status"
            value={status}
            onChange={(event) => setStatus(event.target.value as TemplateStatus)}
            style={styles.select}
          >
            {TEMPLATE_STATUSES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <span style={styles.meta}>
            v{version}
            {dirty ? " · unsaved" : ""}
          </span>
          <button type="button" onClick={handleSave} disabled={busy} style={styles.primaryButton}>
            {busy ? "Working…" : "Save"}
          </button>
        </div>
        {error ? <p style={styles.error}>{error}</p> : null}
        {notice ? <p style={styles.notice}>{notice}</p> : null}
      </header>

      <div style={styles.grid}>
        <section style={styles.editorPane}>
          <div ref={containerRef} style={styles.canvas} />
        </section>

        <aside style={styles.sidePane}>
          <section style={styles.card}>
            <h2 style={styles.cardTitle}>Personalization</h2>
            <p style={styles.hint}>
              Variables are escaped by the server. Use{" "}
              <code>{"{{ name }}"}</code> or <code>{'{{ name | default: "…" }}'}</code>.
            </p>
            {PERSONALIZATION_VARIABLES.map((variable) => (
              <label key={variable} style={styles.field}>
                <span style={styles.fieldLabel}>{variable}</span>
                <input
                  value={values[variable] ?? ""}
                  onChange={(event) =>
                    setValues((current) => ({ ...current, [variable]: event.target.value }))
                  }
                  placeholder={`{{ ${variable} }}`}
                  style={styles.input}
                />
              </label>
            ))}
          </section>

          <section style={styles.card}>
            <div style={styles.cardHeader}>
              <h2 style={styles.cardTitle}>Preview</h2>
              <div role="group" aria-label="Preview width" style={styles.deviceGroup}>
                {DEVICES.map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    onClick={() => setDevice(entry.id)}
                    style={entry.id === device ? styles.deviceActive : styles.deviceButton}
                  >
                    {entry.label}
                  </button>
                ))}
              </div>
            </div>
            <button
              type="button"
              onClick={handlePreview}
              disabled={busy || !canPreview}
              style={styles.secondaryButton}
            >
              Render preview
            </button>
            {!canPreview ? (
              <p style={styles.hint}>Save the template to render a server-side preview.</p>
            ) : null}
            {preview ? (
              <>
                {preview.missing.length > 0 ? (
                  <p style={styles.error}>
                    Missing values: {preview.missing.join(", ")}
                  </p>
                ) : null}
                {preview.used_fallback.length > 0 ? (
                  <p style={styles.warning}>
                    Using fallback defaults: {preview.used_fallback.join(", ")}
                  </p>
                ) : null}
                <div style={styles.frameWrap}>
                  <iframe
                    title="Rendered email preview"
                    // Scripts are already stripped server-side; the sandbox is
                    // defence in depth and gives the preview an isolated origin.
                    sandbox=""
                    srcDoc={preview.html}
                    style={{
                      width: frameWidth === 0 ? "100%" : `${frameWidth}px`,
                      minHeight: 420,
                      border: "1px solid #2a2f3a",
                      background: "#ffffff",
                    }}
                  />
                </div>
                <details style={styles.details}>
                  <summary>Plaintext alternative</summary>
                  <pre style={styles.pre}>{preview.text}</pre>
                </details>
              </>
            ) : null}
          </section>

          <section style={styles.card}>
            <h2 style={styles.cardTitle}>Test send</h2>
            <p style={styles.hint}>
              Restricted to verified addresses. No production campaign is enqueued.
            </p>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>Recipient</span>
              <input
                type="email"
                value={recipient}
                onChange={(event) => setRecipient(event.target.value)}
                placeholder="you@example.com"
                style={styles.input}
              />
            </label>
            <label style={styles.field}>
              <span style={styles.fieldLabel}>Subject</span>
              <input
                value={subject}
                onChange={(event) => setSubject(event.target.value)}
                style={styles.input}
              />
            </label>
            <button
              type="button"
              onClick={handleTestSend}
              disabled={busy || !canPreview || !recipient || !subject}
              style={styles.secondaryButton}
            >
              Send test
            </button>
          </section>

          <section style={styles.card}>
            <h2 style={styles.cardTitle}>Supported components</h2>
            <p style={styles.hint}>
              The server rejects anything outside this set, including raw HTML or script blocks.
            </p>
            <div style={styles.chips}>
              {SUPPORTED_MJML_COMPONENTS.map((component) => (
                <span key={component} style={styles.chip}>
                  {component}
                </span>
              ))}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}

const styles: Record<string, CSSProperties> = {
  header: { marginBottom: 16 },
  headerRow: { display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" },
  nameInput: {
    flex: "1 1 240px",
    minWidth: 200,
    padding: "8px 10px",
    background: "#141822",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
  },
  select: {
    padding: "8px 10px",
    background: "#141822",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
  },
  meta: { color: "#9aa4b2", fontSize: 13 },
  primaryButton: {
    padding: "8px 16px",
    background: "#2f6feb",
    color: "#fff",
    border: "none",
    borderRadius: 6,
    cursor: "pointer",
  },
  secondaryButton: {
    width: "100%",
    padding: "8px 12px",
    background: "#1b2130",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
    cursor: "pointer",
  },
  grid: {
    display: "grid",
    gridTemplateColumns: "minmax(0, 1fr) 380px",
    gap: 16,
    alignItems: "start",
  },
  editorPane: {
    border: "1px solid #2a2f3a",
    borderRadius: 8,
    overflow: "hidden",
    background: "#fff",
    height: 720,
  },
  canvas: { height: "100%" },
  sidePane: { display: "flex", flexDirection: "column", gap: 16 },
  card: {
    border: "1px solid #2a2f3a",
    borderRadius: 8,
    padding: 16,
    background: "#10141c",
  },
  cardHeader: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 8,
    marginBottom: 8,
  },
  cardTitle: { margin: "0 0 8px", fontSize: 15 },
  hint: { margin: "0 0 12px", color: "#9aa4b2", fontSize: 12, lineHeight: 1.5 },
  field: { display: "block", marginBottom: 10 },
  fieldLabel: { display: "block", fontSize: 12, color: "#9aa4b2", marginBottom: 4 },
  input: {
    width: "100%",
    padding: "7px 9px",
    background: "#141822",
    color: "inherit",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
    boxSizing: "border-box",
  },
  deviceGroup: { display: "flex", gap: 4 },
  deviceButton: {
    padding: "4px 8px",
    fontSize: 12,
    background: "transparent",
    color: "#9aa4b2",
    border: "1px solid #2a2f3a",
    borderRadius: 6,
    cursor: "pointer",
  },
  deviceActive: {
    padding: "4px 8px",
    fontSize: 12,
    background: "#2f6feb",
    color: "#fff",
    border: "1px solid #2f6feb",
    borderRadius: 6,
    cursor: "pointer",
  },
  frameWrap: { marginTop: 12, overflow: "auto", textAlign: "center" },
  details: { marginTop: 12, color: "#9aa4b2", fontSize: 12 },
  pre: {
    whiteSpace: "pre-wrap",
    wordBreak: "break-word",
    background: "#0b0d12",
    padding: 10,
    borderRadius: 6,
    color: "#c8d0dc",
    fontSize: 12,
  },
  chips: { display: "flex", flexWrap: "wrap", gap: 6 },
  chip: {
    padding: "2px 8px",
    fontSize: 11,
    border: "1px solid #2a2f3a",
    borderRadius: 999,
    color: "#9aa4b2",
  },
  error: { color: "#ff8a8a", fontSize: 13, margin: "8px 0 0" },
  warning: { color: "#e3b341", fontSize: 13, margin: "8px 0 0" },
  notice: { color: "#6fcf97", fontSize: 13, margin: "8px 0 0" },
};
