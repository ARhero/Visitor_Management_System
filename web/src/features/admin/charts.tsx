/**
 * Small hand-written charts (no chart library: the admin bundle stays light and the
 * visitor/guard bundles never load these).
 *
 * Every chart here is a single series in the brand teal, so no legend box is needed:
 * the card title says what is plotted. Marks follow one spec: columns at most 24px
 * wide with a 4px rounded top and a square base, hairline solid gridlines, text in
 * ink tokens (never the mark color), a hover tooltip on every mark, and a table view.
 */
import { useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { cx } from "@/components/ui";

const MARK = "var(--color-brand)";
// One-hue teal ramp for magnitude (heatmap), light → dark.
const RAMP = ["#e3eef0", "#b9d5db", "#86b4be", "#4f8c9a", "#2a6878", "#0f4c5c"];

export const fmt = (n: number) => (n >= 10_000 ? `${(n / 1000).toFixed(n >= 100_000 ? 0 : 1)}K` : n.toLocaleString("en-IN"));

export function duration(s: number | null | undefined): string {
  if (s === null || s === undefined) return "–";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return m < 10 ? `${m}m ${String(s % 60).padStart(2, "0")}s` : `${m}m`;
  return `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}

function niceMax(v: number): number {
  if (v <= 4) return Math.max(v, 1);
  const mag = 10 ** Math.floor(Math.log10(v));
  for (const k of [1, 2, 2.5, 5, 10]) if (k * mag >= v) return k * mag;
  return 10 * mag;
}

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [w, setW] = useState(600);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, Math.floor(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, w] as const;
}

export function StatTile({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "warn" }) {
  return (
    <div className="rounded-[var(--radius-card)] border border-line bg-surface px-4 py-3">
      <p className="text-xs text-ink-3">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums tracking-tight", tone === "warn" ? "text-warn" : "text-ink")}>{value}</p>
      {hint && <p className="mt-0.5 text-xs text-ink-3">{hint}</p>}
    </div>
  );
}

export interface Col {
  label: string; // axis label
  value: number;
  title?: string; // tooltip heading (defaults to label)
  detail?: string[]; // extra tooltip lines
}

/** Vertical columns with a hover tooltip. */
export function Columns({ data, height = 180, unit = "", label, every }: { data: Col[]; height?: number; unit?: string; label: string; every?: number }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const padL = 34;
  const padB = 22;
  const innerW = width - padL - 4;
  const innerH = height - padB - 8;
  const top = niceMax(Math.max(0, ...data.map((d) => d.value)));
  const ticks = [0, top / 2, top].filter((v, i, a) => a.indexOf(v) === i && Number.isInteger(v));
  const slot = innerW / Math.max(data.length, 1);
  const bw = Math.min(24, Math.max(2, slot * 0.68));
  const y = (v: number) => 8 + innerH - (v / top) * innerH;
  const step = every ?? Math.max(1, Math.ceil(data.length / Math.floor(innerW / 44)));
  const maxIdx = data.reduce((m, d, i) => (d.value > data[m].value ? i : m), 0);
  const h = hover !== null ? data[hover] : null;

  return (
    <div ref={ref} className="relative" onMouseLeave={() => setHover(null)}>
      <svg width={width} height={height} role="img" aria-label={label} className="block overflow-visible">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={width - 4} y1={y(t)} y2={y(t)} stroke="var(--color-line)" strokeWidth={1} />
            <text x={padL - 6} y={y(t)} dy="0.32em" textAnchor="end" className="fill-ink-3 text-[10px] tabular-nums">{fmt(t)}</text>
          </g>
        ))}
        {data.map((d, i) => {
          const x = padL + i * slot + (slot - bw) / 2;
          const bh = Math.max(0, y(0) - y(d.value));
          const r = Math.min(4, bh, bw / 2);
          const top_ = y(0) - bh;
          return (
            <g key={i}>
              {bh > 0 && (
                <path
                  d={`M${x},${y(0)} V${top_ + r} Q${x},${top_} ${x + r},${top_} H${x + bw - r} Q${x + bw},${top_} ${x + bw},${top_ + r} V${y(0)} Z`}
                  fill={MARK}
                  opacity={hover === null || hover === i ? 1 : 0.55}
                />
              )}
              {i === maxIdx && d.value > 0 && (
                <text x={x + bw / 2} y={top_ - 4} textAnchor="middle" className="fill-ink-2 text-[10px] font-medium tabular-nums">{fmt(d.value)}</text>
              )}
              {i % step === 0 && (
                <text x={padL + i * slot + slot / 2} y={height - 6} textAnchor="middle" className="fill-ink-3 text-[10px]">{d.label}</text>
              )}
              {/* Hit target: the whole slot, taller than the mark. */}
              <rect x={padL + i * slot} y={0} width={slot} height={height - padB} fill="transparent" onMouseEnter={() => setHover(i)} onFocus={() => setHover(i)} tabIndex={-1} />
            </g>
          );
        })}
      </svg>
      {h && hover !== null && (
        <div
          className="pointer-events-none absolute z-10 min-w-28 -translate-x-1/2 rounded-lg border border-line bg-surface px-3 py-2 text-xs shadow-lg"
          style={{ left: Math.min(Math.max(padL + hover * slot + slot / 2, 60), width - 60), top: Math.max(0, y(h.value) - 64) }}
          role="tooltip"
        >
          <p className="font-medium text-ink">{h.title ?? h.label}</p>
          <p className="tabular-nums text-ink-2">{fmt(h.value)}{unit}</p>
          {h.detail?.map((l) => <p key={l} className="text-ink-3">{l}</p>)}
        </div>
      )}
      <TableView headers={["", label]} rows={data.map((d) => [d.title ?? d.label, `${fmt(d.value)}${unit}`])} />
    </div>
  );
}

/** Ranked horizontal bars, values at the tips. */
export function HBars({ data, unit = "", empty = "No data for this period" }: { data: { label: string; value: number; sub?: string }[]; unit?: string; empty?: string }) {
  if (!data.length) return <p className="py-6 text-center text-sm text-ink-3">{empty}</p>;
  const top = Math.max(1, ...data.map((d) => d.value));
  return (
    <ul className="space-y-2">
      {data.map((d) => (
        <li key={d.label} className="grid grid-cols-[minmax(0,38%)_1fr] items-center gap-3 text-sm" title={`${d.label}: ${fmt(d.value)}${unit}`}>
          <span className="truncate text-ink-2">{d.label}{d.sub && <span className="text-ink-3"> · {d.sub}</span>}</span>
          <span className="flex items-center gap-2">
            <span className="h-2.5 rounded-r-[4px]" style={{ width: `${(d.value / top) * 85}%`, minWidth: d.value ? 3 : 0, background: MARK }} />
            <span className="tabular-nums text-xs text-ink-2">{fmt(d.value)}{unit}</span>
          </span>
        </li>
      ))}
    </ul>
  );
}

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

/** Weekday × hour grid (IST). Color = magnitude on a one-hue ramp; empty = paper. */
export function Heatmap({ grid }: { grid: number[][] }) {
  const [hover, setHover] = useState<[number, number] | null>(null);
  const max = Math.max(1, ...grid.flat());
  const shade = (v: number) => (v === 0 ? "var(--color-paper)" : RAMP[Math.min(RAMP.length - 1, Math.floor((v / max) * (RAMP.length - 1) + 0.5) || 1)]);
  const hrs = Array.from({ length: 24 }, (_, h) => h);
  return (
    <div className="relative" onMouseLeave={() => setHover(null)}>
      <div className="overflow-x-auto">
        <div className="grid min-w-[560px] grid-cols-[34px_repeat(24,minmax(0,1fr))] gap-[2px]" role="img" aria-label="Check-ins by weekday and hour">
          {grid.map((row, w) => (
            <div key={w} className="contents">
              <span className="pr-1 text-right text-[10px] leading-5 text-ink-3">{DAYS[w]}</span>
              {row.map((v, h) => (
                <span key={h} className={cx("h-5 rounded-[3px]", hover?.[0] === w && hover?.[1] === h && "ring-2 ring-ink/60")} style={{ background: shade(v) }} onMouseEnter={() => setHover([w, h])} />
              ))}
            </div>
          ))}
          <span />
          {hrs.map((h) => <span key={h} className="text-center text-[10px] text-ink-3">{h % 3 === 0 ? h : ""}</span>)}
        </div>
      </div>
      <div className="mt-2 flex items-center justify-between text-xs text-ink-3">
        <span>{hover ? `${DAYS[hover[0]]} ${String(hover[1]).padStart(2, "0")}:00–${String(hover[1] + 1).padStart(2, "0")}:00 · ${grid[hover[0]][hover[1]]} check-ins` : "Hover a cell for the count"}</span>
        <span className="flex items-center gap-1">Fewer {RAMP.map((c) => <span key={c} className="inline-block size-3 rounded-[2px]" style={{ background: c }} />)} More</span>
      </div>
      <TableView headers={["", ...hrs.map(String)]} rows={grid.map((r, w) => [DAYS[w], ...r.map(String)])} />
    </div>
  );
}

function TableView({ headers, rows }: { headers: string[]; rows: string[][] }) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-ink-3 hover:text-ink">Show as table</summary>
      <div className="mt-2 max-h-64 overflow-auto rounded border border-line">
        <table className="w-full tabular-nums">
          <thead className="bg-paper"><tr>{headers.map((h, i) => <th key={i} className="px-2 py-1 text-left font-medium text-ink-2">{h}</th>)}</tr></thead>
          <tbody>{rows.map((r, i) => <tr key={i} className="border-t border-line">{r.map((c, j) => <td key={j} className="px-2 py-1 text-ink-2">{c}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </details>
  );
}
