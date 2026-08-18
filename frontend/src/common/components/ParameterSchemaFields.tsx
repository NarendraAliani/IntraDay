// frontend/src/common/components/ParameterSchemaFields.tsx
//
// Checkpoint 27 Part 14/27: the ONE reusable, schema-driven parameter
// control renderer - extracted from StrategyConfigurationPage.tsx
// (Checkpoint 26) so the Backtest Workbench can reuse it verbatim rather
// than duplicating strategy parameter fields (Part 14's own explicit
// instruction: "Do not duplicate strategy fields in the Backtest page").
// Every consumer (Strategy Configuration, Backtest Workbench) renders
// controls purely from a `ParameterDefinition[]` - no per-screen,
// per-strategy hardcoded form exists anywhere in this codebase.
import type { FieldDefinition, ParameterDefinition } from "../api/strategyApi";

export function ParameterControl({
  parameter,
  value,
  onChange,
  fields,
}: {
  parameter: ParameterDefinition;
  value: string;
  onChange: (next: string) => void;
  fields: FieldDefinition[];
}): JSX.Element {
  const inputId = `param-${parameter.parameter_id}`;

  if (parameter.parameter_type === "FIELD_REFERENCE") {
    return (
      <select id={inputId} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select a field…</option>
        {fields.map((field) => (
          <option key={field.field_id} value={field.field_id}>
            {field.display_name}
          </option>
        ))}
      </select>
    );
  }

  if (parameter.parameter_type === "ENUM") {
    return (
      <select id={inputId} value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select…</option>
        {parameter.allowed_values.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    );
  }

  if (parameter.parameter_type === "INTEGER" || parameter.parameter_type === "DECIMAL") {
    return (
      <input
        id={inputId}
        type="number"
        step={parameter.parameter_type === "DECIMAL" ? "any" : "1"}
        value={value}
        min={parameter.minimum != null ? String(parameter.minimum) : undefined}
        max={parameter.maximum != null ? String(parameter.maximum) : undefined}
        // Suggested-value hint (a real user asked for this after having
        // to guess a value for a field with no guidance): the schema's
        // own `default` doubles as a placeholder so it's still visible
        // even once the field holds a real value the user typed.
        placeholder={parameter.default != null ? String(parameter.default) : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    );
  }

  // TIMEFRAME (and any future closed-set string type not yet special-cased)
  return <input id={inputId} type="text" value={value} onChange={(e) => onChange(e.target.value)} />;
}

/** Renders a full parameter list (label + control + help text) for one
 * schema - the shared body both StrategyConfigurationPage and the
 * Backtest Workbench mount inside their own surrounding form. */
export function ParameterSchemaFields({
  parameters,
  values,
  onChange,
  fields,
}: {
  parameters: ParameterDefinition[];
  values: Record<string, string>;
  onChange: (parameterId: string, next: string) => void;
  fields: FieldDefinition[];
}): JSX.Element {
  return (
    <>
      {parameters.map((parameter) => (
        <div className="strategy-config-page__field" key={parameter.parameter_id}>
          <label htmlFor={`param-${parameter.parameter_id}`}>
            {parameter.label}
            {parameter.required ? " *" : ""}
          </label>
          <ParameterControl
            parameter={parameter}
            value={values[parameter.parameter_id] ?? ""}
            onChange={(next) => onChange(parameter.parameter_id, next)}
            fields={fields}
          />
          {parameter.help_text && (
            <p className="strategy-config-page__help-text">{parameter.help_text}</p>
          )}
        </div>
      ))}
    </>
  );
}

/** Builds the initial values map from a schema's own declared defaults -
 * shared by both consumers so "what counts as a default value" is
 * defined in exactly one place. */
export function defaultValuesFor(parameters: ParameterDefinition[]): Record<string, string> {
  const defaults: Record<string, string> = {};
  for (const parameter of parameters) {
    if (parameter.default !== null && parameter.default !== undefined) {
      defaults[parameter.parameter_id] = String(parameter.default);
    }
  }
  return defaults;
}
