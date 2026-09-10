// frontend/src/common/components/Sparkline.tsx
//
// CHECKPOINT-WATCHLIST-B, Phase B of WATCHLIST_REDESIGN_ROADMAP.md: a
// small per-row sparkline, following EquityChart.tsx's own established
// buildPath() idiom exactly (Checkpoint 27 Part 17's "do not introduce
// a huge charting framework without justification" - a single-series,
// axis-less line does not justify one either). No new charting
// dependency - plain inline SVG.
import { useMemo } from "react";

const WIDTH = 96;
const HEIGHT = 28;
const PADDING = 2;

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

/** Renders `closes` (chronological, oldest first - the exact shape
 * `WatchlistInstrumentMarketData.sparkline` already carries) as a tiny
 * trend line. Rising (last >= first) is styled distinctly from falling
 * - color is never the only signal elsewhere in this app, but a
 * sparkline's whole purpose is the shape itself; the up/down class is
 * a supplementary cue, not the sole one (the row's own `change_percent`
 * text carries the same fact in words). Renders a plain dash for an
 * empty/single-point series - never a fabricated flat line implying
 * "no movement" when the truth is "not enough gate-verified data." */
export function Sparkline({ closes }: { closes: string[] }): JSX.Element {
  const values = useMemo(() => closes.map((c) => Number.parseFloat(c)).filter(Number.isFinite), [
    closes,
  ]);
  const path = useMemo(() => buildPath(values, WIDTH, HEIGHT, PADDING), [values]);

  if (values.length < 2) {
    return (
      <span className="sparkline sparkline--empty" aria-hidden="true">
        —
      </span>
    );
  }

  const rising = values[values.length - 1] >= values[0];
  const trendClass = rising ? "sparkline--up" : "sparkline--down";

  return (
    <svg
      viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
      className={`sparkline ${trendClass}`}
      role="img"
      aria-label={`Trend from ${values[0].toFixed(2)} to ${values[values.length - 1].toFixed(2)} over ${values.length} trading day(s)`}
    >
      <path d={path} className="sparkline__line" fill="none" />
    </svg>
  );
}
