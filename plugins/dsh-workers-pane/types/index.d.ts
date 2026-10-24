export type WorkerPhase =
  | 'running'
  | 'stalled'
  | 'finished'
  | 'failed'
  | 'unreadable'

export type WorkerRow = {
  id: string
  shortId: string
  title: string
  phase: WorkerPhase
  rawPhase: string
  startedAt: number | null
  finishedAt: number | null
  lastActivityAt: number | null
  idleMs: number | null
  elapsedMs: number | null
  toolCalls: number | null
  leaseDeadline: number | null
  leaseMs: number | null
  branch: string | null
}

export type WorkerView = {
  rows: WorkerRow[]
  running: number
  stalled: number
  finishedToday: number
  readAt: number
  root: string
  error: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'dsh-workers': {
      view: WorkerView
    }
  }
}
