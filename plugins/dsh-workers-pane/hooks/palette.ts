// One palette for the pane. Phase colours are the v3 sunset/mango/lime set:
// a bright fill (row dots, the mix bar's end stop) with dark text on the chip,
// so every chip clears 4.5:1 on the dark card. Lease colours stay their own
// green/amber/red signal; they are not a phase.

export type StatusTone = 'success' | 'warning' | 'error' | 'muted' | 'info'

export type StatusColour = {
  /** Text on the filled chip: dark on the bright fills, light on grey. */
  fg: string
  /** The chip's fill, the phase colour itself. */
  bg: string
  /** The phase colour for text and glyphs on the dark card. */
  fill: string
  /** Gradient stops: bright end first, then the deep end. */
  light: string
  deep: string
}

export const STATUS: Record<StatusTone, StatusColour> = {
  // running: sunset yellow #ffd166 -> #ff9f1c
  success: {
    fg: '#1c1400',
    bg: '#ffb627',
    fill: '#ffb627',
    light: '#ffd166',
    deep: '#ff9f1c',
  },
  // stalled: mango orange #ffa552 -> #ff7518
  warning: {
    fg: '#1c0d00',
    bg: '#ff8243',
    fill: '#ff8243',
    light: '#ffa552',
    deep: '#ff7518',
  },
  // failed stays red
  error: {
    fg: '#2b0808',
    bg: '#ff5c5c',
    fill: '#ff5c5c',
    light: '#ffa3a3',
    deep: '#e02d2d',
  },
  // cancelled (and an unreadable record) stays grey
  muted: {
    fg: '#f1f5f9',
    bg: '#475569',
    fill: '#94a3b8',
    light: '#cbd5e1',
    deep: '#64748b',
  },
  // finished: lime green #b8f35a -> #32cd32
  info: {
    fg: '#10240a',
    bg: '#9be15d',
    fill: '#9be15d',
    light: '#b8f35a',
    deep: '#32cd32',
  },
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
