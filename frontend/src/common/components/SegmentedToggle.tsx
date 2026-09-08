// frontend/src/common/components/SegmentedToggle.tsx
//
// Checkpoint FRONTEND-3: a small, shared single-select control for a
// FEW real options (radio-button semantics, rendered as a segmented
// button group) - a single click beats opening a dropdown when there
// are only a handful of choices. Genuinely accessible: a real
// `role="radiogroup"`/`role="radio"` pair, not a styled `<div>` with
// `onClick` handlers, so keyboard/screen-reader behavior matches a
// native radio group.
//
// Deliberately falls back to a plain `<select>` past `maxSegments`
// (default 5) - a segmented control gets cramped and hard to scan well
// before it gets genuinely unusable, and this project's own strategy
// registry is expected to grow (more strategies may be registered
// later, per CLAUDE.md's own research-to-registered pipeline). This
// makes that growth safe by construction: no caller needs to remember
// to swap components back to a dropdown themselves.
export interface SegmentedToggleOption {
  value: string;
  label: string;
}

export interface SegmentedToggleProps {
  id: string;
  label: string;
  value: string;
  options: SegmentedToggleOption[];
  onChange: (value: string) => void;
  /** Above this many options, renders a `<select>` instead - a
   * segmented row of >5 buttons stops being faster to scan than a
   * dropdown. */
  maxSegments?: number;
  disabled?: boolean;
}

export function SegmentedToggle(props: SegmentedToggleProps): JSX.Element {
  const maxSegments = props.maxSegments ?? 5;

  if (props.options.length > maxSegments) {
    return (
      <div className="strategy-config-page__field">
        <label htmlFor={props.id}>{props.label}</label>
        <select
          id={props.id}
          value={props.value}
          disabled={props.disabled}
          onChange={(e) => props.onChange(e.target.value)}
        >
          {props.options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>
    );
  }

  return (
    <div className="strategy-config-page__field">
      <span id={`${props.id}-label`}>{props.label}</span>
      <div className="segmented-toggle" role="radiogroup" aria-labelledby={`${props.id}-label`}>
        {props.options.map((option) => {
          const selected = option.value === props.value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={selected}
              disabled={props.disabled}
              className={
                selected ? "segmented-toggle__segment segmented-toggle__segment--selected" : "segmented-toggle__segment"
              }
              onClick={() => props.onChange(option.value)}
            >
              {option.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
