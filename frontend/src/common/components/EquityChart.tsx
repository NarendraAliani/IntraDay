// frontend/src/common/components/EquityChart.tsx
//
// Checkpoint 27 Part 17: lightweight equity/drawdown charts, plain
// inline SVG - no charting framework introduced (Part 17's own
// instruction: "do not introduce a huge charting framework without
// justification"; two simple line charts do not justify one). Axes,
// labels, tooltips (via <title>), responsive (viewBox-based) and
// explicit empty state are all handled here directly.
import { useMemo } from "react";

export interface EquityPoint {
  timestamp: string;
  balance: string;
  drawdown_percent: string;
}

const WIDTH = 640;
const HEIGHT = 220;
const PADDING = 36;

function toNumber(value: string): number {
  const parsed = Number.parseFloat(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function buildPath(values: number[], width: number, height: number, padding: number): string {
  if (values.length === 0) return "";
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = values.length > 1 ? (width - padding * 2) / (values.length - 1) : 0;
  return values
    .map((value, index) => {
      const x = padding + index * stepX;
      const y = height - padding - ((value - min) / range) * (height - padding * 2);
      return `${index === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

function LineChart({
  title,
  values,
  labels,
  formatValue,
  emptyMessage,
}: {
  title: string;
  values: number[];
  labels: string[];
  formatValue: (value: number) => string;
  emptyMessage: string;
}): JSX.Element {
  const path = useMemo(() => buildPath(values, WIDTH, HEIGHT, PADDING), [values]);

  if (values.length === 0) {
    return (
      <div className="equity-chart equity-chart--empty" role="img" aria-label={`${title} - no data`}>
        <p>{emptyMessage}</p>
      </div>
    );
  }

  const min = Math.min(...values);
  const max = Math.max(...values);

  return (
    <figure className="equity-chart">
      <figcaption>{title}</figcaption>
      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        role="img"
        aria-label={`${title} chart from ${formatValue(values[0])} to ${formatValue(values[values.length - 1])}`}
        className="equity-chart__svg"
      >
        <line
          x1={PADDING}
          y1={HEIGHT - PADDING}
          x2={WIDTH - PADDING}
          y2={HEIGHT - PADDING}
          className="equity-chart__axis"
        />
        <line x1={PADDING} y1={PADDING} x2={PADDING} y2={HEIGHT - PADDING} className="equity-chart__axis" />
        <text x={PADDING} y={PADDING - 8} className="equity-chart__axis-label">
          {formatValue(max)}
        </text>
        <text x={PADDING} y={HEIGHT - PADDING + 16} className="equity-chart__axis-label">
          {formatValue(min)}
        </text>
        <text x={WIDTH - PADDING} y={HEIGHT - PADDING + 16} textAnchor="end" className="equity-chart__axis-label">
          {labels[labels.length - 1]}
        </text>
        <path d={path} className="equity-chart__line" fill="none">
          <title>{`${title}: ${formatValue(values[values.length - 1])} at ${labels[labels.length - 1]}`}</title>
        </path>
      </svg>
    </figure>
  );
}

export function EquityCurveChart({ points }: { points: EquityPoint[] }): JSX.Element {
  const values = points.map((p) => toNumber(p.balance));
  const labels = points.map((p) => new Date(p.timestamp).toLocaleString());
  return (
    <LineChart
      title="Equity Curve"
      values={values}
      labels={labels}
      formatValue={(v) => `₹${v.toFixed(0)}`}
      emptyMessage="No equity data - the backtest produced zero trades."
    />
  );
}

export function DrawdownChart({ points }: { points: EquityPoint[] }): JSX.Element {
  const values = points.map((p) => toNumber(p.drawdown_percent));
  const labels = points.map((p) => new Date(p.timestamp).toLocaleString());
  return (
    <LineChart
      title="Drawdown Curve (%)"
      values={values}
      labels={labels}
      formatValue={(v) => `${v.toFixed(2)}%`}
      emptyMessage="No drawdown data - the backtest produced zero trades."
    />
  );
}
