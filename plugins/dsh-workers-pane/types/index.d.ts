export type WorkerPhase =
  | 'running'
  | 'stalled'
  | 'finished'
  | 'failed'
  | 'cancelled'
  | 'unreadable'

export type WorkerKind = 'worker' | 'data_job'

export type WorkerOutcome = 'ok' | 'failed' | 'cancelled'

export type ActivityLine = { time: string; text: string }

/** Lifetime counts rebuilt from `<job>/result.md.events.jsonl`. */
export type EventCounts = {
  toolCalls: number
  modelSteps: number
  outputTokens: number
  /** Distinct files written, newest last, capped like the dsh-worker MCP. */
  recentFiles: string[]
  lastTool: string | null
  lastToolTarget: string | null
  byTool: Record<string, number>
}

/**
 * One job's incremental event scan: the byte offset already consumed, the
 * counts built from those bytes, and the sampling window behind the
 * activity sparkline (events seen per minute, 30 buckets).
 */
export type EventScan = EventCounts & {
  offset: number
  size: number
  lines: number
  unparsedLines: number
  spark: number[]
  sparkAt: number
}

export type ScanCache = { jobs: Record<string, EventScan> }

export type WorkerMetrics = {
  toolCalls: number
  modelSteps: number
  outputTokens: number
  fileWrites: number
  lastTool: string | null
  lastToolTarget: string | null
  byTool: Record<string, number>
}

export type WorkerRow = {
  id: string
  shortId: string
  title: string
  kind: WorkerKind
  phase: WorkerPhase
  rawPhase: string
  outcome: WorkerOutcome | null
  startedAt: number | null
  finishedAt: number | null
  lastActivityAt: number | null
  idleMs: number | null
  elapsedMs: number | null
  metrics: WorkerMetrics | null
  leaseDeadline: number | null
  leaseMs: number | null
  leaseTotalMs: number | null
  branch: string | null
  workspace: string | null
  ownerSession: string | null
  exitCode: number | null
  spark: number[] | null
  /** First lines of brief.md / the task file, for the detail card. */
  briefLines: string[]
  /** Recent heartbeat activity, oldest first. */
  activity: ActivityLine[]
  /** Last lines of result.md, used when there is no heartbeat activity. */
  resultTail: string[]
}

export type WorkerGroup = {
  session: string
  label: string
  rows: WorkerRow[]
  spanMs: number
}

export type WorkerCounts = {
  running: number
  stalled: number
  failed: number
  finished: number
}

export type MetricsMaxima = {
  tools: number
  steps: number
  tokens: number
  files: number
  idle: number
}

export type WorkerView = {
  running: WorkerRow[]
  finished: WorkerRow[]
  finishedGroups: WorkerGroup[]
  counts: WorkerCounts
  maxima: MetricsMaxima
  readAt: number
  root: string
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'dsh-workers': {
      view: WorkerView
      scan: ScanCache
      expandedId: string | null
      finishedOpen: boolean
    }
  }
}
