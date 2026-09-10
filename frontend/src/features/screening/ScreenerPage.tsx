// frontend/src/features/screening/ScreenerPage.tsx
//
// CHECKPOINT-SCANNER-B, Phase B of SCANNER_BUILDER_ROADMAP.md: the
// discretionary, MANUAL screening page. A trader builds a rule (field,
// operator, comparison), picks a universe and a date range, presses
// Run, and looks at which instruments matched - themselves, right now.
//
// ARCHITECTURE BOUNDARY (the roadmap's own explicit instruction): this
// is a NEW, standalone page under its own `features/screening/`
// directory - never embedded inside `StrategyConfigurationPage`,
// `BacktestingWorkbenchPage`, or the Live Paper Operations Console.
// It shares only genuinely generic UI primitives
// (`InstrumentPickerMulti`, the `FIELD_REFERENCE` dropdown pattern
// `ParameterSchemaFields.tsx` already established, `Pagination`-style
// shared components) - it never imports anything strategy- or paper-
// trading-specific.
//
// HISTORICAL MODE ONLY this phase - no mention of live/real-time
// anywhere in this page's copy (Phase C's own concern, gated behind an
// active worker session per SCANNER_BUILDER_ROADMAP.md's own Part 1
// finding 4).
import { useEffect, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { evaluateScreeningRule } from "../../common/api/screeningApi";
import type {
  ScreeningConditionRequest,
  ScreeningEvaluateResponse,
  ScreeningInstrumentResult,
} from "../../common/api/screeningApi";
import { getFieldRegistry } from "../../common/api/strategyApi";
import type { FieldDefinition } from "../../common/api/strategyApi";
import { ErrorState } from "../../common/components/ErrorState";
import { InstrumentPickerMulti } from "../../common/components/InstrumentPicker";
import { LoadingState } from "../../common/components/LoadingState";

type Operator = ">" | "<" | ">=" | "<=" | "==";
const OPERATORS: Operator[] = [">", "<", ">=", "<=", "=="];

interface ConditionDraft {
  fieldId: string;
  operator: Operator;
  comparison: string;
}

function newCondition(defaultFieldId: string): ConditionDraft {
  return { fieldId: defaultFieldId, operator: ">", comparison: "" };
}

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

function todayIsoDate(): string {
  return new Date().toISOString().slice(0, 10);
}

function statusBadgeClass(status: ScreeningInstrumentResult["status"]): string {
  if (status === "MATCHED") return "badge badge--active";
  if (status === "NOT_GATE_VERIFIED") return "badge badge--pending";
  return "badge badge--historical";
}

function statusLabel(status: ScreeningInstrumentResult["status"]): string {
  if (status === "MATCHED") return "Matched";
  if (status === "NOT_GATE_VERIFIED") return "Not verified";
  return "No match";
}

/** One condition row - a field picker (reusing the SAME `FieldDefinition`
 * registry `ParameterSchemaFields.tsx`'s own `FIELD_REFERENCE` dropdown
 * already drives), an operator picker, and a free-text comparison box
 * (accepts a number for a constant, or another field_id like `ema_20`
 * for a field-vs-field condition - the backend resolves which, exactly
 * as `evaluate_condition()`'s own docstring documents). */
function ConditionRow({
  condition,
  fields,
  onChange,
  onRemove,
  removable,
}: {
  condition: ConditionDraft;
  fields: FieldDefinition[];
  onChange: (next: ConditionDraft) => void;
  onRemove: () => void;
  removable: boolean;
}): JSX.Element {
  return (
    <div className="form-row screener-page__condition-row">
      <label>
        Field
        <select
          value={condition.fieldId}
          onChange={(e) => onChange({ ...condition, fieldId: e.target.value })}
        >
          {fields.map((field) => (
            <option key={field.field_id} value={field.field_id}>
              {field.display_name}
            </option>
          ))}
        </select>
      </label>
      <label>
        Operator
        <select
          value={condition.operator}
          onChange={(e) => onChange({ ...condition, operator: e.target.value as Operator })}
        >
          {OPERATORS.map((op) => (
            <option key={op} value={op}>
              {op}
            </option>
          ))}
        </select>
      </label>
      <label>
        Compare to
        <input
          type="text"
          placeholder="e.g. 30, or ema_20"
          value={condition.comparison}
          onChange={(e) => onChange({ ...condition, comparison: e.target.value })}
        />
      </label>
      <button type="button" onClick={onRemove} disabled={!removable}>
        Remove
      </button>
    </div>
  );
}

export function ScreenerPage(): JSX.Element {
  const [fields, setFields] = useState<FieldDefinition[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [conditions, setConditions] = useState<ConditionDraft[]>([newCondition("close")]);
  const [combinator, setCombinator] = useState<"AND" | "OR">("AND");
  const [instrumentIds, setInstrumentIds] = useState<string[]>([]);
  const [timeframe, setTimeframe] = useState("5m");
  const [startDate, setStartDate] = useState(todayIsoDate());
  const [endDate, setEndDate] = useState(todayIsoDate());

  const [running, setRunning] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [result, setResult] = useState<ScreeningEvaluateResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const fieldList = await getFieldRegistry();
        if (cancelled) return;
        setFields(fieldList);
      } catch (error) {
        if (cancelled) return;
        setLoadError(describeError(error));
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  function updateCondition(index: number, next: ConditionDraft): void {
    setConditions((prev) => prev.map((c, i) => (i === index ? next : c)));
  }

  function removeCondition(index: number): void {
    setConditions((prev) => prev.filter((_, i) => i !== index));
  }

  function addCondition(): void {
    setConditions((prev) => [...prev, newCondition(fields?.[0]?.field_id ?? "close")]);
  }

  const canRun =
    conditions.length > 0 &&
    conditions.every((c) => c.comparison.trim() !== "") &&
    instrumentIds.length > 0 &&
    startDate !== "" &&
    endDate !== "";

  async function handleRun(): Promise<void> {
    if (!canRun) return;
    setRunning(true);
    setRunError(null);
    setResult(null);
    try {
      const requestConditions: ScreeningConditionRequest[] = conditions.map((c) => ({
        field_id: c.fieldId,
        operator: c.operator,
        comparison: c.comparison.trim(),
      }));
      const response = await evaluateScreeningRule({
        conditions: requestConditions,
        combinator,
        instrument_ids: instrumentIds,
        timeframe,
        start_date: startDate,
        end_date: endDate,
      });
      setResult(response);
    } catch (error) {
      setRunError(describeError(error));
    } finally {
      setRunning(false);
    }
  }

  if (loadError) return <ErrorState message={loadError} />;
  if (!fields) return <LoadingState label="Loading field registry…" />;

  return (
    <div className="screener-page">
      <h1>Screener</h1>
      <p className="configuration-viewer__subtitle">
        Build a rule, run it against real historical bars, and see which instruments match right
        now. This is a manual exploration tool you run and read yourself - it never generates a
        signal, never places an order, and is not connected to paper trading.
      </p>
      <span className="badge badge--historical badge--inline">Historical mode</span>

      <section aria-label="Rule builder">
        <h2>Rule</h2>
        {conditions.map((condition, index) => (
          <ConditionRow
            key={index}
            condition={condition}
            fields={fields}
            onChange={(next) => updateCondition(index, next)}
            onRemove={() => removeCondition(index)}
            removable={conditions.length > 1}
          />
        ))}
        <div className="form-row">
          <button type="button" onClick={addCondition}>
            Add condition
          </button>
          {conditions.length > 1 && (
            <label>
              Combine with
              <select
                value={combinator}
                onChange={(e) => setCombinator(e.target.value as "AND" | "OR")}
              >
                <option value="AND">AND — every condition must match</option>
                <option value="OR">OR — any condition may match</option>
              </select>
            </label>
          )}
        </div>
      </section>

      <section aria-label="Universe and date range">
        <h2>Universe and range</h2>
        <InstrumentPickerMulti
          value={instrumentIds}
          onChange={setInstrumentIds}
          idPrefix="screener"
          label="Instruments"
        />
        <div className="form-grid">
          <label>
            Timeframe
            <select value={timeframe} onChange={(e) => setTimeframe(e.target.value)}>
              <option value="1m">1 minute</option>
              <option value="5m">5 minutes</option>
              <option value="15m">15 minutes</option>
              <option value="1h">1 hour</option>
            </select>
          </label>
          <label>
            Start date
            <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </label>
          <label>
            End date
            <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
          </label>
        </div>
      </section>

      <button type="button" onClick={() => void handleRun()} disabled={!canRun || running}>
        {running ? "Running…" : "Run"}
      </button>

      {runError && <ErrorState message={runError} />}

      {result && (
        <section aria-label="Results">
          <h2>Results</h2>
          <p>
            {result.matched_count} of {result.evaluated_count} evaluated instrument(s) matched.
            {result.not_gate_verified_count > 0 && (
              <>
                {" "}
                {result.not_gate_verified_count} instrument(s) could not be checked — see "Not
                verified" below.
              </>
            )}
          </p>
          <div className="table-scroll">
            <table className="market-data-monitor__table">
              <thead>
                <tr>
                  <th scope="col">Instrument</th>
                  <th scope="col">Status</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {result.results.map((row) => (
                  <tr key={row.instrument_id}>
                    <td>{row.instrument_id}</td>
                    <td>
                      <span className={statusBadgeClass(row.status)}>{statusLabel(row.status)}</span>
                    </td>
                    <td>
                      {row.status === "MATCHED" &&
                        (row.matched_condition_details ?? []).map((detail, i) => (
                          <div key={i}>{detail}</div>
                        ))}
                      {row.status === "NOT_GATE_VERIFIED" && row.coverage_detail}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </div>
  );
}
