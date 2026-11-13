"use client";

/**
 * Segment condition editor.
 *
 * Mirrors the server-side segment AST (`app/domain/audience/segments.py`): only
 * the field/operator combinations the API accepts are offered, so an operator
 * cannot compose a definition that validation will reject.
 */

import {
  CONSENT_STATUSES,
  CONTACT_STATUSES,
  type SegmentCondition,
  type SegmentDefinition,
  type SegmentMatch,
  type TagOut,
} from "@email-platform/api-client";
import { Field, splitList, styles } from "@/components/ui";

/** Editor-only shape: list values are held as comma-separated text. */
export interface ConditionDraft {
  field: string;
  operator: string;
  key: string;
  value: string;
}

interface FieldSpec {
  value: string;
  label: string;
  operators: { value: string; label: string }[];
}

const FIELD_SPECS: FieldSpec[] = [
  {
    value: "status",
    label: "Contact status",
    operators: [
      { value: "eq", label: "is" },
      { value: "ne", label: "is not" },
      { value: "in", label: "is any of" },
      { value: "not_in", label: "is none of" },
    ],
  },
  {
    value: "consent_status",
    label: "Consent status",
    operators: [
      { value: "eq", label: "is" },
      { value: "ne", label: "is not" },
      { value: "in", label: "is any of" },
      { value: "not_in", label: "is none of" },
    ],
  },
  {
    value: "created_at",
    label: "Created at",
    operators: [
      { value: "gt", label: "after" },
      { value: "gte", label: "on or after" },
      { value: "lt", label: "before" },
      { value: "lte", label: "on or before" },
    ],
  },
  {
    value: "updated_at",
    label: "Updated at",
    operators: [
      { value: "gt", label: "after" },
      { value: "gte", label: "on or after" },
      { value: "lt", label: "before" },
      { value: "lte", label: "on or before" },
    ],
  },
  {
    value: "attribute",
    label: "Attribute",
    operators: [
      { value: "eq", label: "equals" },
      { value: "ne", label: "does not equal" },
      { value: "in", label: "is any of" },
      { value: "not_in", label: "is none of" },
      { value: "contains", label: "contains" },
      { value: "exists", label: "exists" },
    ],
  },
  {
    value: "tag",
    label: "Tag",
    operators: [
      { value: "has", label: "has" },
      { value: "not_has", label: "does not have" },
    ],
  },
];

const LIST_OPERATORS = new Set(["in", "not_in"]);

function operatorsFor(field: string): string[] {
  const spec = FIELD_SPECS.find((item) => item.value === field);
  return spec ? spec.operators.map((operator) => operator.value) : ["eq"];
}

export function emptyDraft(): ConditionDraft {
  return { field: "status", operator: "eq", key: "", value: "" };
}

function toDraft(condition: SegmentCondition): ConditionDraft {
  const raw = condition.value;
  const value =
    raw === undefined || raw === null
      ? ""
      : Array.isArray(raw)
        ? raw.map((item) => String(item)).join(", ")
        : String(raw);
  return {
    field: condition.field,
    operator: condition.operator,
    key: condition.key ?? "",
    value,
  };
}

export function toDrafts(definition: SegmentDefinition): ConditionDraft[] {
  return definition.conditions.map(toDraft);
}

function draftToCondition(draft: ConditionDraft): SegmentCondition {
  if (draft.field === "attribute") {
    if (draft.operator === "exists") {
      return { field: "attribute", key: draft.key, operator: "exists" };
    }
    return {
      field: "attribute",
      key: draft.key,
      operator: draft.operator,
      value: LIST_OPERATORS.has(draft.operator) ? splitList(draft.value) : draft.value,
    };
  }
  if (draft.field === "tag") {
    return { field: "tag", operator: draft.operator, value: draft.value };
  }
  if (draft.field === "status" || draft.field === "consent_status") {
    return {
      field: draft.field,
      operator: draft.operator,
      value: LIST_OPERATORS.has(draft.operator) ? splitList(draft.value) : draft.value,
    };
  }
  return { field: draft.field, operator: draft.operator, value: draft.value };
}

export function buildDefinition(
  match: SegmentMatch,
  drafts: ConditionDraft[],
): SegmentDefinition {
  return { match, conditions: drafts.map(draftToCondition) };
}

interface SegmentBuilderProps {
  match: SegmentMatch;
  onMatchChange: (match: SegmentMatch) => void;
  drafts: ConditionDraft[];
  onDraftsChange: (drafts: ConditionDraft[]) => void;
  tags: TagOut[];
}

function valueKind(field: string, operator: string): "none" | "list" | "enum" | "datetime" | "tag" | "text" {
  if (field === "attribute" && operator === "exists") {
    return "none";
  }
  if (field === "tag") {
    return "tag";
  }
  if (field === "status" || field === "consent_status") {
    return LIST_OPERATORS.has(operator) ? "list" : "enum";
  }
  if (field === "created_at" || field === "updated_at") {
    return "datetime";
  }
  return LIST_OPERATORS.has(operator) ? "list" : "text";
}

export default function SegmentBuilder({
  match,
  onMatchChange,
  drafts,
  onDraftsChange,
  tags,
}: SegmentBuilderProps) {
  function update(index: number, patch: Partial<ConditionDraft>) {
    onDraftsChange(
      drafts.map((draft, position) => (position === index ? { ...draft, ...patch } : draft)),
    );
  }

  function changeField(index: number, field: string) {
    const operators = operatorsFor(field);
    update(index, { field, operator: operators[0], key: "", value: "" });
  }

  function changeOperator(index: number, operator: string) {
    update(index, { operator, value: "" });
  }

  return (
    <div>
      <Field label="Match">
        <select
          style={styles.select}
          value={match}
          onChange={(event) => onMatchChange(event.target.value as SegmentMatch)}
        >
          <option value="all">all conditions</option>
          <option value="any">any condition</option>
        </select>
      </Field>

      {drafts.map((draft, index) => {
        const kind = valueKind(draft.field, draft.operator);
        const enumValues: readonly string[] =
          draft.field === "status" ? CONTACT_STATUSES : CONSENT_STATUSES;
        return (
          <div key={index} style={{ ...styles.card, padding: 12 }}>
            <div style={styles.row}>
              <Field label="Field">
                <select
                  style={styles.select}
                  value={draft.field}
                  onChange={(event) => changeField(index, event.target.value)}
                >
                  {FIELD_SPECS.map((spec) => (
                    <option key={spec.value} value={spec.value}>
                      {spec.label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Operator">
                <select
                  style={styles.select}
                  value={draft.operator}
                  onChange={(event) => changeOperator(index, event.target.value)}
                >
                  {(FIELD_SPECS.find((spec) => spec.value === draft.field)?.operators ?? []).map(
                    (operator) => (
                      <option key={operator.value} value={operator.value}>
                        {operator.label}
                      </option>
                    ),
                  )}
                </select>
              </Field>
              {draft.field === "attribute" ? (
                <Field label="Attribute key">
                  <input
                    style={styles.input}
                    value={draft.key}
                    onChange={(event) => update(index, { key: event.target.value })}
                    placeholder="company"
                  />
                </Field>
              ) : null}
              {kind === "none" ? null : (
                <Field
                  label="Value"
                  hint={kind === "list" ? "Comma-separated" : undefined}
                >
                  {kind === "enum" ? (
                    <select
                      style={styles.select}
                      value={draft.value}
                      onChange={(event) => update(index, { value: event.target.value })}
                    >
                      <option value="">select a value</option>
                      {enumValues.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  ) : kind === "tag" ? (
                    <select
                      style={styles.select}
                      value={draft.value}
                      onChange={(event) => update(index, { value: event.target.value })}
                    >
                      <option value="">select a tag</option>
                      {tags.map((tag) => (
                        <option key={tag.id} value={tag.id}>
                          {tag.name}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      style={styles.input}
                      type={kind === "datetime" ? "datetime-local" : "text"}
                      value={draft.value}
                      onChange={(event) => update(index, { value: event.target.value })}
                      placeholder={kind === "list" ? "active, unsubscribed" : ""}
                    />
                  )}
                </Field>
              )}
              <button
                type="button"
                style={styles.danger}
                onClick={() => onDraftsChange(drafts.filter((_, position) => position !== index))}
              >
                Remove
              </button>
            </div>
          </div>
        );
      })}

      <button
        type="button"
        style={styles.secondary}
        onClick={() => onDraftsChange([...drafts, emptyDraft()])}
      >
        Add condition
      </button>
    </div>
  );
}
