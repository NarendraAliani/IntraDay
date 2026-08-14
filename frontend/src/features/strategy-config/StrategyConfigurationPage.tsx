// frontend/src/features/strategy-config/StrategyConfigurationPage.tsx
//
// Checkpoint 26 Part 13/18: the Strategy Configuration screen. ONE
// generic, schema-driven renderer - deliberately NOT `EmaForm.tsx` /
// `SmaTrendForm.tsx` / `AtrBreakoutForm.tsx`. Every control (Strategy
// dropdown, per-parameter input) is generated purely from what the API
// returns (`listStrategies()`, `getStrategySchema()`, `getFieldRegistry()`)
// - no hardcoded strategy list, no hardcoded parameter list anywhere in
// this file (Part 4/6: single canonical source of truth, consumed
// end-to-end from Strategy -> Parameter Schema -> API -> this renderer).
//
// Dependent-dropdown behavior (Part 6): switching the selected strategy
// invalidates and clears every parameter value from the PREVIOUS
// strategy's schema - a stale `fast_lookback` value from EMA Crossover
// must never silently survive a switch to SMA Trend Filter, whose
// schema doesn't even define that parameter_id.
import { useEffect, useMemo, useState } from "react";

import { ApiNetworkError, ApiRequestError } from "../../common/api/client";
import { useAuth } from "../../common/auth/AuthContext";
import { ErrorState } from "../../common/components/ErrorState";
import { LoadingState } from "../../common/components/LoadingState";
import { ParameterSchemaFields, defaultValuesFor } from "../../common/components/ParameterSchemaFields";
import {
  getFieldRegistry,
  getStrategySchema,
  listConfigurations,
  listStrategies,
  saveConfiguration,
} from "../../common/api/strategyApi";
import type {
  FieldDefinition,
  StrategyConfigurationResponse,
  StrategySchema,
  StrategySummary,
} from "../../common/api/strategyApi";

type LoadState =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "ready"; strategies: StrategySummary[]; fields: FieldDefinition[] };

type SaveState = { phase: "idle" } | { phase: "saving" } | { phase: "error"; message: string };

function describeError(error: unknown): string {
  if (error instanceof ApiRequestError || error instanceof ApiNetworkError) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

export function StrategyConfigurationPage(): JSX.Element {
  const { state: authState } = useAuth();
  const canWrite =
    authState.status === "authenticated" &&
    authState.capabilities.includes("configuration.activate");

  const [loadState, setLoadState] = useState<LoadState>({ phase: "loading" });
  const [selectedStrategyId, setSelectedStrategyId] = useState<string>("");
  const [schema, setSchema] = useState<StrategySchema | null>(null);
  const [schemaError, setSchemaError] = useState<string | null>(null);
  const [values, setValues] = useState<Record<string, string>>({});
  const [savedConfigurations, setSavedConfigurations] = useState<
    StrategyConfigurationResponse[]
  >([]);
  const [configurationVersion, setConfigurationVersion] = useState("");
  const [saveState, setSaveState] = useState<SaveState>({ phase: "idle" });

  useEffect(() => {
    let cancelled = false;
    async function load(): Promise<void> {
      try {
        const [strategies, fields] = await Promise.all([listStrategies(), getFieldRegistry()]);
        if (cancelled) return;
        setLoadState({ phase: "ready", strategies, fields });
        if (strategies.length > 0) {
          setSelectedStrategyId(strategies[0].strategy_id);
        }
      } catch (error) {
        if (cancelled) return;
        setLoadState({ phase: "error", message: describeError(error) });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  // Dependent-dropdown behavior (Part 6): reload the schema and clear
  // every previously-entered value whenever the selected strategy
  // changes - a stale value from a DIFFERENT strategy's schema must
  // never survive the switch.
  useEffect(() => {
    if (!selectedStrategyId) return;
    let cancelled = false;
    setValues({});
    setSchema(null);
    setSchemaError(null);
    setSavedConfigurations([]);
    async function loadSchema(): Promise<void> {
      try {
        const [strategySchema, configurations] = await Promise.all([
          getStrategySchema(selectedStrategyId),
          listConfigurations(selectedStrategyId),
        ]);
        if (cancelled) return;
        setSchema(strategySchema);
        setSavedConfigurations(configurations);
        setValues(defaultValuesFor(strategySchema.parameters));
      } catch (error) {
        if (cancelled) return;
        setSchemaError(describeError(error));
      }
    }
    void loadSchema();
    return () => {
      cancelled = true;
    };
  }, [selectedStrategyId]);

  const selectedStrategy = useMemo(() => {
    if (loadState.phase !== "ready") return undefined;
    return loadState.strategies.find((s) => s.strategy_id === selectedStrategyId);
  }, [loadState, selectedStrategyId]);

  if (loadState.phase === "loading") {
    return <LoadingState label="Loading strategies…" />;
  }
  if (loadState.phase === "error") {
    return <ErrorState message={loadState.message} />;
  }

  const { strategies, fields } = loadState;

  async function handleSave(): Promise<void> {
    if (!schema || !configurationVersion.trim() || !selectedStrategy) return;
    setSaveState({ phase: "saving" });
    try {
      const parsedValues: Record<string, unknown> = {};
      for (const parameter of schema.parameters) {
        const raw = values[parameter.parameter_id];
        if (raw === undefined || raw === "") continue;
        if (parameter.parameter_type === "INTEGER") {
          parsedValues[parameter.parameter_id] = Number.parseInt(raw, 10);
        } else if (parameter.parameter_type === "DECIMAL") {
          parsedValues[parameter.parameter_id] = raw;
        } else {
          parsedValues[parameter.parameter_id] = raw;
        }
      }
      const saved = await saveConfiguration(selectedStrategyId, {
        specification_version: selectedStrategy.specification_version,
        code_version: selectedStrategy.code_version,
        configuration_version: configurationVersion.trim(),
        values: parsedValues,
      });
      setSavedConfigurations((prev) => [...prev, saved]);
      setConfigurationVersion("");
      setSaveState({ phase: "idle" });
    } catch (error) {
      setSaveState({ phase: "error", message: describeError(error) });
    }
  }

  return (
    <div className="strategy-config-page">
      <h1>Strategy Configuration</h1>
      <p className="configuration-viewer__subtitle">
        Configure and version strategy parameters. Activating a configuration prepares it for
        research, simulation, or backtesting only - it does NOT authorize live trading, which
        remains governed separately by risk controls and the SAMPLE_BAR data-quality gate (market
        data is not yet trading-grade - see Live Market Data Monitor).
      </p>

      <div className="strategy-config-page__field">
        <label htmlFor="strategy-select">Strategy</label>
        <select
          id="strategy-select"
          value={selectedStrategyId}
          onChange={(e) => setSelectedStrategyId(e.target.value)}
        >
          {strategies.map((strategy) => (
            <option key={strategy.strategy_id} value={strategy.strategy_id}>
              {strategy.display_name}
              {strategy.is_active ? " (active)" : ""}
            </option>
          ))}
        </select>
      </div>

      {schemaError && <ErrorState message={schemaError} />}

      {schema && (
        <form
          className="strategy-config-page__form"
          onSubmit={(e) => {
            e.preventDefault();
            void handleSave();
          }}
        >
          <fieldset>
            <legend>Parameters</legend>
            <ParameterSchemaFields
              parameters={schema.parameters}
              values={values}
              onChange={(parameterId, next) =>
                setValues((prev) => ({ ...prev, [parameterId]: next }))
              }
              fields={fields}
            />
          </fieldset>

          {canWrite && (
            <div className="strategy-config-page__field">
              <label htmlFor="configuration-version">Configuration Version</label>
              <input
                id="configuration-version"
                type="text"
                placeholder="e.g. cfg-v1"
                value={configurationVersion}
                onChange={(e) => setConfigurationVersion(e.target.value)}
              />
              <button type="submit" disabled={!configurationVersion.trim() || saveState.phase === "saving"}>
                {saveState.phase === "saving" ? "Saving…" : "Save Configuration"}
              </button>
              {!configurationVersion.trim() && (
                <p className="strategy-config-page__help-text">
                  Enter a configuration version label to enable Save.
                </p>
              )}
              {saveState.phase === "error" && <ErrorState message={saveState.message} />}
            </div>
          )}
          {!canWrite && (
            <p className="strategy-config-page__help-text">
              You have read-only access - saving configurations requires the configuration-operator
              role.
            </p>
          )}
        </form>
      )}

      <section className="strategy-config-page__saved">
        <h2>Saved Configurations</h2>
        {savedConfigurations.length === 0 && <p>No configurations saved yet for this strategy.</p>}
        {savedConfigurations.length > 0 && (
          <table>
            <thead>
              <tr>
                <th>Version</th>
                <th>Values</th>
                <th>Created</th>
                <th>By</th>
              </tr>
            </thead>
            <tbody>
              {savedConfigurations.map((config) => (
                <tr key={config.configuration_version}>
                  <td>{config.configuration_version}</td>
                  <td>{JSON.stringify(config.values)}</td>
                  <td>{new Date(config.created_at).toLocaleString()}</td>
                  <td>{config.created_by}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
