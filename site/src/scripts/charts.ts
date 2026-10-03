import * as Plot from '@observablehq/plot';
import { MESES, reais, reaisCurto } from '../lib/format';

export function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

/** Render with the current theme; re-render on resize and theme change. */
export function mount(el: HTMLElement | null, render: (width: number) => Element | null) {
  if (!el) return;
  let last = 0;
  const draw = () => {
    const width = Math.max(280, Math.floor(el.clientWidth));
    const node = render(width);
    el.replaceChildren(...(node ? [node] : []));
    last = width;
  };
  draw();
  const ro = new ResizeObserver(() => {
    if (Math.abs(el.clientWidth - last) > 8) draw();
  });
  ro.observe(el);
  window.addEventListener('themechange', draw);
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', draw);
}

function baseStyle() {
  return {
    background: 'transparent',
    color: cssVar('--text-2'),
    fontSize: '12px',
    fontFamily: 'Inter, system-ui, sans-serif',
    overflow: 'visible',
  };
}

export interface MonthPoint { ano: number; mes: number; total: number }

/** Monthly spending as columns over time (single series). */
export function monthlyChart(data: MonthPoint[], width: number, height = 260) {
  const rows = data.map((d) => ({ ...d, date: new Date(Date.UTC(d.ano, d.mes - 1, 1)) }));
  const fill = cssVar('--series-1');
  // Label the first month present of each year (data may start in February).
  const firstOfYear = new Set<number>();
  const seen = new Set<number>();
  for (const r of rows) if (!seen.has(r.ano)) { seen.add(r.ano); firstOfYear.add(r.date.getTime()); }
  const showMonths = rows.length <= 14;
  return Plot.plot({
    width, height, marginLeft: 56, marginBottom: 30, marginTop: 12,
    style: baseStyle(),
    x: { type: 'band', label: null, tickSize: 0,
         tickFormat: (d: Date) => (showMonths ? MESES[d.getUTCMonth()] : firstOfYear.has(d.getTime()) ? String(d.getUTCFullYear()) : '') },
    y: { label: null, grid: true, tickFormat: (v: number) => reaisCurto(v).replace('R$ ', ''), ticks: 5 },
    marks: [
      Plot.gridY({ stroke: cssVar('--grid'), strokeOpacity: 1 }),
      Plot.barY(rows, {
        x: 'date', y: 'total', fill, rx2: 3, insetLeft: 1, insetRight: 1,
        title: (d: any) => `${MESES[d.mes - 1]}/${d.ano}\n${reais(d.total)}`,
        tip: { fill: cssVar('--surface'), stroke: cssVar('--border') },
      }),
      Plot.ruleY([0], { stroke: cssVar('--text-3') }),
    ],
  });
}

export interface BarDatum { label: string; value: number; extra?: string; href?: string }

/** Horizontal bars, sorted, with direct value labels. */
export function hbarChart(data: BarDatum[], width: number, opts: { color?: string; labelWidth?: number } = {}) {
  const fill = opts.color ?? cssVar('--series-1');
  const narrow = width < 420;
  const marginLeft = opts.labelWidth ?? (narrow ? 150 : 200);
  const height = Math.max(120, data.length * 30 + 24);
  const max = Math.max(...data.map((d) => d.value), 1);
  return Plot.plot({
    width, height, marginLeft, marginRight: 76, marginTop: 4, marginBottom: 20,
    style: baseStyle(),
    x: { axis: null, domain: [0, max] },
    y: { label: null, domain: data.map((d) => d.label), tickSize: 0,
         tickFormat: (s: string) => (s.length > (narrow ? 22 : 30) ? s.slice(0, narrow ? 21 : 29) + '…' : s) },
    marks: [
      Plot.barX(data, {
        x: 'value', y: 'label', fill, rx2: 3, insetTop: 5, insetBottom: 5,
        title: (d: BarDatum) => `${d.label}\n${reais(d.value)}${d.extra ? '\n' + d.extra : ''}`,
        tip: { fill: cssVar('--surface'), stroke: cssVar('--border') },
        href: data.some((d) => d.href) ? (d: BarDatum) => d.href : undefined,
      }),
      Plot.text(data, {
        x: 'value', y: 'label', text: (d: BarDatum) => reaisCurto(d.value), dx: 6,
        textAnchor: 'start', fill: cssVar('--text-2'), fontVariant: 'tabular-nums',
      }),
    ],
  });
}
