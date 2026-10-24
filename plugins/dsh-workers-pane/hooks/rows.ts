// Pure job-record -> pane-row logic. No `$` here, so the rules are testable
// without IO: register.tsx reads the files, this module decides what they mean.

import type { WorkerPhase, WorkerRow, WorkerView } from '../types'

export type { WorkerPhase, WorkerRow, WorkerView }

export type StatusMeta = {
  id: string
  rawPhase: string
  phase: WorkerPhase
  startedAt: number | null
  finishedAt: number | null
  lastActivityAt: number | null
}

export const STALL_MS = 20 * 60 * 1000
export const LEASE_WARN_MS = 15 * 60 * 1000

export const EMPTY_VIEW: WorkerView = {
  rows: [],
  running: 0,
  stalled: 0,
  finishedToday: 0,
  readAt: 0,
  root: '',
  error: null,
}

const FINAL_PHASES = new Set([
  'finished',
  'failed',
  'cancelled',
  'lost',
  'orphaned',
])

function obj(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value.trim() : null
}

function firstString(...values: unknown[]): string | null {
  for (const value of values) {
    const found = str(value)
    if (found !== null) return found
  }
  return null
}

export function isoMs(value: unknown): number | null {
  if (typeof value !== 'string') return null
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? null : parsed
}

export function isDataJobStatus(status: unknown): boolean {
  return obj(status)?.['kind'] === 'data_job'
}

function firstIso(...values: unknown[]): number | null {
  for (const value of values) {
    const found = isoMs(value)
    if (found !== null) return found
  }
  return null
}

function arrayOf(value: unknown): unknown[] | null {
  return Array.isArray(value) ? value : null
}

function oneLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

function clip(value: string, limit: number): string {
  return value.length <= limit ? value : `${value.slice(0, limit - 1)}…`
}

function cleanBriefLine(value: string | null): string | null {
  if (value === null) return null
  const clean = oneLine(
    value.replace(/^#+\s*/, '').replace(/^task\s*[:\-–—]\s*/i, ''),
  )
  return clean === '' ? null : clean
}

function firstLineOf(value: string | null): string | null {
  if (value === null) return null
  for (const line of value.split(/\r?\n/)) {
    if (line.trim() !== '') return line
  }
  return null
}

function taskFileTitle(value: string | null): string | null {
  if (value === null) return null
  const name = value.split(/[\\/]/).pop() ?? ''
  const title = oneLine(name.replace(/\.[A-Za-z0-9]+$/, '').replace(/_/g, ' '))
  return title === '' ? null : title
}

function titleOf(
  id: string,
  job: Record<string, unknown> | null,
  brief: string | null,
): string {
  const dataJob = obj(job?.['data_job'])
  const fromJob = firstString(job?.['brief_first_line'])
  const fromBrief = firstLineOf(brief)
  const title =
    firstString(dataJob?.['name'], job?.['name']) ??
    cleanBriefLine(fromJob) ??
    cleanBriefLine(fromBrief) ??
    taskFileTitle(firstString(job?.['task_file'])) ??
    id.slice(-8)
  return clip(title, 100)
}

function phaseOf(
  rawPhase: string,
  lastActivityAt: number | null,
  now: number,
): WorkerPhase {
  if (rawPhase === '' || rawPhase === 'unknown') return 'unreadable'
  if (rawPhase === 'failed') return 'failed'
  if (FINAL_PHASES.has(rawPhase)) return 'finished'
  if (lastActivityAt !== null && now - lastActivityAt > STALL_MS) {
    return 'stalled'
  }
  return 'running'
}

export function statusMeta(
  id: string,
  status: unknown,
  now: number,
  logMtimeMs: number | null = null,
): StatusMeta {
  const record = obj(status)
  const rawPhase = (str(record?.['phase']) ?? '').toLowerCase()
  const startedAt = isoMs(record?.['started_at'])
  const updatedAt = isoMs(record?.['updated_at'])
  const live = obj(record?.['heartbeat_live'])
  const liveActivity = firstIso(
    live?.['last_worker_activity_at'],
    live?.['last_activity_at'],
    record?.['worker_activity_at'],
  )
  // A data job publishes no heartbeat; its stdout/stderr mtime is the only
  // progress signal it has.
  const fallbackActivity =
    logMtimeMs === null
      ? startedAt
      : Math.max(logMtimeMs, startedAt ?? logMtimeMs)
  const lastActivityAt = liveActivity ?? fallbackActivity
  const finishedAt =
    isoMs(record?.['finished_at']) ??
    (FINAL_PHASES.has(rawPhase) ? updatedAt : null)

  return {
    id,
    rawPhase: rawPhase === '' ? 'unreadable' : rawPhase,
    phase: phaseOf(rawPhase, lastActivityAt, now),
    startedAt,
    finishedAt,
    lastActivityAt,
  }
}

/** A `status.json` missing its phase because the run failed before the
 * supervisor wrote one: classify it as the failed job it is, not as a live
 * unreadable one. */
export function failedStartMeta(
  meta: StatusMeta,
  job: unknown,
): StatusMeta {
  const record = obj(job)
  if (record?.['start_failed'] !== true) return meta
  const created = isoMs(record['created_at']) ?? meta.startedAt
  return {
    ...meta,
    rawPhase: 'failed',
    phase: 'failed',
    startedAt: created,
    finishedAt: created,
  }
}

export function pickRows(
  metas: readonly StatusMeta[],
  finishedLimit = 8,
): StatusMeta[] {
  const active = metas
    .filter(
      meta =>
        meta.phase === 'running' ||
        meta.phase === 'stalled' ||
        meta.phase === 'unreadable',
    )
    .sort(
      (a, b) =>
        (b.startedAt ?? 0) - (a.startedAt ?? 0) || b.id.localeCompare(a.id),
    )
  const finals = metas
    .filter(meta => meta.phase === 'finished' || meta.phase === 'failed')
    .sort(
      (a, b) =>
        (b.finishedAt ?? 0) - (a.finishedAt ?? 0) || b.id.localeCompare(a.id),
    )

  return [...active, ...finals.slice(0, finishedLimit)]
}

export function rowOf(
  id: string,
  status: unknown,
  job: unknown,
  heartbeat: unknown,
  brief: string | null,
  now: number,
  logMtimeMs: number | null = null,
): WorkerRow {
  const meta = statusMeta(id, status, now, logMtimeMs)
  const statusRecord = obj(status)
  const jobRecord = obj(job)
  const heartbeatRecord = obj(heartbeat)
  const heartbeatInner = obj(heartbeatRecord?.['heartbeat']) ?? heartbeatRecord

  const events =
    arrayOf(heartbeatInner?.['events']) ?? arrayOf(heartbeatRecord?.['events'])
  const toolCalls =
    events === null
      ? null
      : events.filter(event => obj(event)?.['kind'] === 'tool_call').length

  const lastActivityAt =
    firstIso(
      heartbeatInner?.['last_worker_activity_at'],
      heartbeatInner?.['last_activity_at'],
      heartbeatRecord?.['last_worker_activity_at'],
      heartbeatRecord?.['last_activity_at'],
    ) ?? meta.lastActivityAt
  const lease = obj(statusRecord?.['controller_lease'])
  const leaseDeadline = isoMs(lease?.['deadline'])
  const leaseMs = leaseDeadline === null ? null : leaseDeadline - now

  const worktree = obj(jobRecord?.['worktree'])
  const branch =
    worktree !== null && worktree['enabled'] !== false
      ? str(worktree['branch'])
      : null

  const end =
    meta.phase === 'finished' || meta.phase === 'failed'
      ? (meta.finishedAt ?? meta.startedAt)
      : now
  const elapsedMs =
    meta.startedAt === null || end === null
      ? null
      : Math.max(0, end - meta.startedAt)
  const idleMs =
    lastActivityAt === null ? null : Math.max(0, now - lastActivityAt)

  return {
    id,
    shortId: id.slice(-8),
    title: titleOf(id, jobRecord, brief),
    phase: meta.phase,
    rawPhase: meta.rawPhase,
    startedAt: meta.startedAt,
    finishedAt: meta.finishedAt,
    lastActivityAt,
    idleMs,
    elapsedMs,
    toolCalls,
    leaseDeadline,
    leaseMs,
    branch,
  }
}

export function isToday(at: number, now: number): boolean {
  const a = new Date(at)
  const b = new Date(now)
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

export function viewOf(
  rows: WorkerRow[],
  metas: readonly StatusMeta[],
  now: number,
  root: string,
  error: string | null,
): WorkerView {
  return {
    rows,
    running: metas.filter(meta => meta.phase === 'running').length,
    stalled: metas.filter(meta => meta.phase === 'stalled').length,
    finishedToday: metas.filter(
      meta =>
        meta.phase === 'finished' &&
        meta.finishedAt !== null &&
        isToday(meta.finishedAt, now),
    ).length,
    readAt: now,
    root,
    error,
  }
}

export function formatDuration(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '–'
  const seconds = Math.max(0, Math.floor(ms / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m`
  const hours = Math.floor(minutes / 60)
  if (hours < 48) {
    const rest = minutes % 60
    return rest === 0 ? `${hours}h` : `${hours}h${String(rest).padStart(2, '0')}`
  }
  return `${Math.floor(hours / 24)}d`
}

export function formatLease(ms: number | null): string {
  if (ms === null) return '–'
  return ms < 0 ? `-${formatDuration(-ms)}` : formatDuration(ms)
}

export function leaseColor(ms: number | null): 'error' | undefined {
  return ms !== null && ms < LEASE_WARN_MS ? 'error' : undefined
}

export function phaseGlyph(phase: WorkerPhase): string {
  switch (phase) {
    case 'running':
      return '●'
    case 'stalled':
      return '◐'
    case 'failed':
      return '✕'
    case 'finished':
      return '○'
    case 'unreadable':
      return '?'
  }
}

export function phaseColor(
  phase: WorkerPhase,
): 'success' | 'warning' | 'error' | undefined {
  switch (phase) {
    case 'running':
      return 'success'
    case 'stalled':
      return 'warning'
    case 'failed':
      return 'error'
    case 'finished':
    case 'unreadable':
      return undefined
  }
}
