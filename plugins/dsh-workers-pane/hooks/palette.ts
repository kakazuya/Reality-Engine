// One palette for the pane. Hex values are tuned for the dark theme; status
// labels use ThemeKey colours where the theme should win (success/warning/
// error/subtle/merged) and filled chips carry explicit dark backgrounds with
// light text so they stay readable on a light theme too.

export type StatusTone = 'success' | 'warning' | 'error' | 'muted' | 'info'

export const STATUS: Record<
  StatusTone,
  { fg: string; bg: string; fill: string; light: string }
> = {
  success: { fg: '#bbf7d0', bg: '#166534', fill: '#22c55e', light: '#86efac' },
  warning: { fg: '#fde68a', bg: '#78350f', fill: '#f59e0b', light: '#fde68a' },
  error: { fg: '#fecaca', bg: '#7f1d1d', fill: '#ef4444', light: '#fecaca' },
  muted: { fg: '#cbd5e1', bg: '#334155', fill: '#64748b', light: '#94a3b8' },
  info: { fg: '#bfdbfe', bg: '#1e3a8a', fill: '#3b82f6', light: '#93c5fd' },
}

export const C = {
  title: '#f8fafc',
  subtitle: '#94a3b8',
  headerTop: '#13213d',
  headerMid: '#0f1b33',
  headerLow: '#0b1428',
  card: '#0f172a',
  cardEdge: '#1e293b',
  cardTitle: '#e2e8f0',
  track: '#1e293b',
  axis: '#334155',
  heatLow: '#152238',
  heatHigh: '#0e7490',
  heatFg: '#e0f2fe',
  spark: '#38bdf8',
  sparkTop: '#4ade80',
  bar: '#38bdf8',
  barTrack: '#1e293b',
  branch: '#c084fc',
  job: '#fbbf24',
  jobFg: '#1c1917',
  result: '#94a3b8',
  leaseTrack: '#1e293b',
  leaseGreen: '#22c55e',
  leaseGreenLight: '#86efac',
  leaseAmber: '#f59e0b',
  leaseAmberLight: '#fde68a',
  leaseRed: '#ef4444',
  leaseRedLight: '#fecaca',
} as const

export function leasePalette(tone: 'success' | 'warning' | 'error'): {
  fill: string
  light: string
} {
  if (tone === 'error') return { fill: C.leaseRed, light: C.leaseRedLight }
  if (tone === 'warning') return { fill: C.leaseAmber, light: C.leaseAmberLight }
  return { fill: C.leaseGreen, light: C.leaseGreenLight }
}

/** 0..1 heat: deeper colour for a bigger value, capped at the row maximum. */
export function heatColor(ratio: number | null): string {
  const value = ratio === null || !Number.isFinite(ratio) ? 0 : Math.max(0, Math.min(1, ratio))
  return value <= 0 ? C.heatLow : mixHex(C.heatLow, C.heatHigh, 0.25 + value * 0.75)
}

export function mixHex(from: string, to: string, ratio: number): string {
  const a = parseHex(from)
  const b = parseHex(to)
  const t = Math.max(0, Math.min(1, ratio))
  const channel = (x: number, y: number): string =>
    Math.round(x + (y - x) * t)
      .toString(16)
      .padStart(2, '0')
  return `#${channel(a[0], b[0])}${channel(a[1], b[1])}${channel(a[2], b[2])}`
}

function parseHex(hex: string): [number, number, number] {
  const clean = hex.replace('#', '')
  return [
    parseInt(clean.slice(0, 2), 16),
    parseInt(clean.slice(2, 4), 16),
    parseInt(clean.slice(4, 6), 16),
  ]
}
