// Pure job-record -> pane-row logic. No `$` here, so the rules are testable
// without IO: register.tsx reads the files, this module decides what they
// mean. Event counting lives in events.ts.

import type {
  ActivityLine,
  MetricsMaxima,
  WorkerCounts,
  WorkerGroup,
  WorkerKind,
  WorkerMetrics,
  WorkerOutcome,
  WorkerPhase,
  WorkerRow,
  WorkerView,
} from '../types'
import { STATUS } from './palette'

export type { WorkerPhase, WorkerRow, WorkerView }

export type StatusMeta = {
  id: string
  kind: WorkerKind
  rawPhase: string
  phase: WorkerPhase
  outcome: WorkerOutcome | null
  exitCode: number | null
  startedAt: number | null
  finishedAt: number | null
  lastActivityAt: number | null
}

export type RowExtras = {
  /** A pre-classified meta (failed start, data-job log mtime) to reuse. */
  meta?: StatusMeta
  metrics?: WorkerMetrics | null
  spark?: number[] | null
  activity?: ActivityLine[]
  resultTail?: string[]
}

export const STALL_MS = 20 * 60 * 1000
export const IDLE_WARN_MS = 10 * 60 * 1000
export const LEASE_WARN_MS = 15 * 60 * 1000
export const LEASE_WATCH_MS = 30 * 60 * 1000

const MONTHS = [
  'Jan',
  'Feb',
  'Mar',
  'Apr',
  'May',
  'Jun',
  'Jul',
  'Aug',
  'Sep',
  'Oct',
  'Nov',
  'Dec',
]

const FINAL_PHASES = new Set([
  'finished',
  'failed',
  'cancelled',
  'lost',
  'orphaned',
])

/** Relative-load floors so a quiet one-job pane does not shade every tile max. */
export const METRIC_FLOORS = {
  tools: 20,
  steps: 10,
  tokens: 50_000,
  files: 5,
  idle: 30,
}

export const EMPTY_VIEW: WorkerView = {
  running: [],
  finished: [],
  finishedGroups: [],
  counts: { running: 0, stalled: 0, failed: 0, finished: 0 },
  maxima: {
    tools: METRIC_FLOORS.tools,
    steps: METRIC_FLOORS.steps,
    tokens: METRIC_FLOORS.tokens,
    files: METRIC_FLOORS.files,
    idle: METRIC_FLOORS.idle,
  },
  readAt: 0,
  root: '',
  error: null,
}

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

function num(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function arrayOf(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

export function isoMs(value: unknown): number | null {
  if (typeof value !== 'string') return null
  const parsed = Date.parse(value)
  return Number.isNaN(parsed) ? null : parsed
}

function firstIso(...values: unknown[]): number | null {
  for (const value of values) {
    const found = isoMs(value)
    if (found !== null) return found
  }
  return null
}

function oneLine(value: string): string {
  return value.replace(/\s+/g, ' ').trim()
}

export function clip(value: string, limit: number): string {
  return value.length <= limit
    ? value
    : `${value.slice(0, Math.max(0, limit - 1))}…`
}

function cleanBriefLine(value: string | null): string | null {
  if (value === null) return null
  const clean = oneLine(
    value.replace(/^#+\s*/, '').replace(/^task\s*[:\-–—]\s*/i, ''),
  )
  return clean === '' ? null : clean
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
  const title =
    firstString(dataJob?.['name'], job?.['name']) ??
    cleanBriefLine(fromJob) ??
    cleanBriefLine(firstNonEmptyLine(brief)) ??
    taskFileTitle(firstString(job?.['task_file'])) ??
    id.slice(-8)
  return clip(title, 120)
}

function firstNonEmptyLine(value: string | null): string | null {
  if (value === null) return null
  for (const line of value.split(/\r?\n/)) {
    if (line.trim() !== '') return line
  }
  return null
}

/** First `limit` real lines of brief.md, or the record's stored first line. */
export function briefLinesOf(
  brief: string | null,
  job: Record<string, unknown> | null,
  limit = 3,
): string[] {
  const lines: string[] = []
  for (const line of (brief ?? '').split(/\r?\n/)) {
    const clean = cleanBriefLine(line)
    if (clean === null) continue
    lines.push(clip(clean, 140))
    if (lines.length >= limit) return lines
  }
  const fromJob = cleanBriefLine(firstString(job?.['brief_first_line']))
  if (lines.length === 0 && fromJob !== null) lines.push(clip(fromJob, 140))
  const dataJob = obj(job?.['data_job'])
  const description = cleanBriefLine(firstString(dataJob?.['description']))
  if (lines.length < limit && description !== null) {
    lines.push(clip(description, 140))
  }
  const task = taskFileTitle(firstString(job?.['task_file']))
  if (lines.length < limit && task !== null) lines.push(clip(task, 140))
  return lines.slice(0, limit)
}

/** Last `limit` non-empty lines of result.md, clipped for the output area. */
export function resultTailOf(text: string | null, limit = 8): string[] {
  if (text === null) return []
  const all: string[] = []
  for (const line of text.split(/\r?\n/)) {
    const clean = oneLine(line)
    if (clean !== '') all.push(clip(clean, 160))
  }
  return all.slice(-Math.max(1, limit))
}

function clockOf(value: unknown): string {
  if (typeof value !== 'string') return ''
  const match = /T(\d{2}:\d{2}:\d{2})/.exec(value)
  return match?.[1] ?? ''
}

/**
 * The newest heartbeat activity as short lines (oldest first): tool calls,
 * text/thinking/final marks. Tool targets are only known for the newest tool
 * call, from the event scan.
 */
export function activityLinesOf(
  events: readonly unknown[],
  metrics: WorkerMetrics | null,
  limit = 8,
): ActivityLine[] {
  const lines: ActivityLine[] = []
  for (const raw of events) {
    const event = obj(raw)
    if (event === null) continue
    const kind = str(event['kind']) ?? str(event['type'])
    const detail = obj(event['detail'])
    const time = clockOf(event['at'])
    let text: string | null = null
    if (kind === 'tool_call') {
      const tool = firstString(detail?.['tool'], event['tool'], event['name'])
      text = `⚙ ${tool ?? 'tool'}`
    } else if (kind === 'text') {
      const chars = num(detail?.['chars']) ?? 0
      text = `✎ text ${chars > 0 ? `${chars}c` : ''}`.trim()
    } else if (kind === 'thinking') {
      text = '◇ thinking'
    } else if (kind === 'final') {
      text = '✓ final'
    }
    if (text !== null) lines.push({ time, text })
  }
  const tail = lines.slice(-Math.max(0, limit))
  const newest = tail[tail.length - 1]
  if (
    newest !== undefined &&
    newest.text.startsWith('⚙') &&
    metrics?.lastToolTarget != null
  ) {
    newest.text = `${newest.text} → ${clip(metrics.lastToolTarget, 48)}`
  }
  return tail
}

function eventsOf(heartbeat: unknown, status: unknown): unknown[] {
  const heartbeatRecord = obj(heartbeat)
  const inner = obj(heartbeatRecord?.['heartbeat']) ?? heartbeatRecord
  const fromHeartbeat = arrayOf(inner?.['events'])
  if (fromHeartbeat.length > 0) return fromHeartbeat
  const live = obj(obj(status)?.['heartbeat_live'])
  return arrayOf(live?.['events'])
}

/**
 * Seed the 30-minute sparkline from heartbeat event timestamps, for a job the
 * pane just opened on (the incremental sampler has no history yet).
 */
export function sparkFromEvents(
  events: readonly unknown[],
  now: number,
  buckets = 30,
): number[] | null {
  const spark = Array.from({ length: buckets }, () => 0)
  let seen = false
  for (const raw of events) {
    const at = isoMs(obj(raw)?.['at'])
    if (at === null) continue
    const age = Math.floor((now - at) / 60_000)
    if (age < 0 || age >= buckets) continue
    spark[buckets - 1 - age] = (spark[buckets - 1 - age] ?? 0) + 1
    seen = true
  }
  return seen ? spark : null
}

function phaseOf(
  rawPhase: string,
  lastActivityAt: number | null,
  now: number,
): WorkerPhase {
  if (rawPhase === '' || rawPhase === 'unknown') return 'unreadable'
  if (rawPhase === 'cancelled') return 'cancelled'
  if (rawPhase === 'failed' || rawPhase === 'lost' || rawPhase === 'orphaned') {
    return 'failed'
  }
  if (FINAL_PHASES.has(rawPhase)) return 'finished'
  if (lastActivityAt !== null && now - lastActivityAt > STALL_MS) {
    return 'stalled'
  }
  return 'running'
}

function outcomeOf(
  phase: WorkerPhase,
  rawOutcome: string | null,
  exitCode: number | null,
): WorkerOutcome | null {
  if (phase === 'cancelled') return 'cancelled'
  if (phase === 'failed') return 'failed'
  if (phase !== 'finished') return null
  const outcome = (rawOutcome ?? '').toLowerCase()
  if (outcome === 'cancelled' || outcome === 'canceled') return 'cancelled'
  if (outcome === 'failed' || outcome === 'error') return 'failed'
  if (exitCode !== null && exitCode !== 0) return 'failed'
  return 'ok'
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
  const final = FINAL_PHASES.has(rawPhase)
  const finishedAt = isoMs(record?.['finished_at']) ?? (final ? updatedAt : null)
  const phase = phaseOf(rawPhase, lastActivityAt, now)
  const exitCode = num(record?.['exit_code'])

  return {
    id,
    kind: record?.['kind'] === 'data_job' ? 'data_job' : 'worker',
    rawPhase: rawPhase === '' ? 'unreadable' : rawPhase,
    phase,
    outcome: outcomeOf(phase, str(record?.['outcome']), exitCode),
    exitCode,
    startedAt,
    finishedAt,
    lastActivityAt,
  }
}

/** A `status.json` missing its phase because the run failed before the
 * supervisor wrote one: classify it as the failed job it is, not as a live
 * unreadable one. */
export function failedStartMeta(meta: StatusMeta, job: unknown): StatusMeta {
  const record = obj(job)
  if (record?.['start_failed'] !== true) return meta
  const created = isoMs(record['created_at']) ?? meta.startedAt
  return {
    ...meta,
    kind: record['kind'] === 'data_job' ? 'data_job' : meta.kind,
    rawPhase: 'failed',
    phase: 'failed',
    outcome: 'failed',
    startedAt: created,
    finishedAt: created,
  }
}

export function isActivePhase(phase: WorkerPhase): boolean {
  return phase === 'running' || phase === 'stalled' || phase === 'unreadable'
}

export function isFinalPhase(phase: WorkerPhase): boolean {
  return phase === 'finished' || phase === 'failed' || phase === 'cancelled'
}

function leaseTotalOf(lease: Record<string, unknown> | null): number | null {
  const seconds = num(lease?.['lease_seconds'])
  if (seconds !== null && seconds > 0) return seconds * 1000
  const start = firstIso(lease?.['renewed_at'], lease?.['created_at'])
  const end = isoMs(lease?.['deadline'])
  return start === null || end === null ? null : Math.max(0, end - start)
}

export function leaseFraction(
  remainingMs: number | null,
  totalMs: number | null,
): number | null {
  if (remainingMs === null || totalMs === null || totalMs <= 0) return null
  return Math.max(0, Math.min(1, remainingMs / totalMs))
}

export function leaseTone(
  fraction: number | null,
  remainingMs: number | null,
): 'success' | 'warning' | 'error' {
  if (remainingMs !== null && remainingMs <= LEASE_WARN_MS) return 'error'
  if (fraction !== null && fraction <= 0.1) return 'error'
  if (remainingMs !== null && remainingMs <= LEASE_WATCH_MS) return 'warning'
  if (fraction !== null && fraction <= 0.35) return 'warning'
  return 'success'
}

export function idleTone(
  idleMs: number | null,
): 'error' | 'warning' | undefined {
  if (idleMs === null) return undefined
  if (idleMs > STALL_MS) return 'error'
  if (idleMs > IDLE_WARN_MS) return 'warning'
  return undefined
}

export function rowOf(
  id: string,
  status: unknown,
  job: unknown,
  heartbeat: unknown,
  brief: string | null,
  now: number,
  logMtimeMs: number | null = null,
  extras: RowExtras = {},
): WorkerRow {
  const meta = extras.meta ?? statusMeta(id, status, now, logMtimeMs)
  const statusRecord = obj(status)
  const jobRecord = obj(job)
  const heartbeatRecord = obj(heartbeat)
  const heartbeatInner = obj(heartbeatRecord?.['heartbeat']) ?? heartbeatRecord

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
  const leaseTotalMs = leaseTotalOf(lease)

  const worktree = obj(jobRecord?.['worktree'])
  const branch =
    worktree !== null && worktree['enabled'] !== false
      ? str(worktree['branch'])
      : null

  const final = isFinalPhase(meta.phase)
  const end = final ? (meta.finishedAt ?? meta.startedAt) : now
  const elapsedMs =
    meta.startedAt === null || end === null
      ? null
      : Math.max(0, end - meta.startedAt)
  const idleMs =
    lastActivityAt === null ? null : Math.max(0, now - lastActivityAt)
  const metrics = extras.metrics ?? null
  const events = eventsOf(heartbeat, status)
  const activity = extras.activity ?? activityLinesOf(events, metrics)
  const spark =
    extras.spark !== undefined &&
    extras.spark !== null &&
    extras.spark.some(value => value > 0)
      ? extras.spark
      : sparkFromEvents(events, now)

  return {
    id,
    shortId: id.slice(-8),
    title: titleOf(id, jobRecord, brief),
    kind: meta.kind,
    phase: meta.phase,
    rawPhase: meta.rawPhase,
    outcome: meta.outcome,
    startedAt: meta.startedAt,
    finishedAt: meta.finishedAt,
    lastActivityAt,
    idleMs,
    elapsedMs,
    metrics,
    leaseDeadline,
    leaseMs,
    leaseTotalMs,
    branch,
    workspace: firstString(jobRecord?.['workspace']),
    ownerSession: firstString(
      statusRecord?.['owner_session'],
      jobRecord?.['owner_session'],
    ),
    exitCode: meta.exitCode,
    spark,
    briefLines: briefLinesOf(brief, jobRecord),
    activity,
    resultTail: extras.resultTail ?? [],
  }
}

function byStartedDesc(a: WorkerRow, b: WorkerRow): number {
  return (b.startedAt ?? 0) - (a.startedAt ?? 0) || b.id.localeCompare(a.id)
}

function byFinishedDesc(a: WorkerRow, b: WorkerRow): number {
  return (
    (b.finishedAt ?? 0) - (a.finishedAt ?? 0) || b.id.localeCompare(a.id)
  )
}

export function sessionLabel(session: string | null): string {
  if (session === null) return 'unknown session'
  const parts = session.split('-').filter(part => part !== '')
  if (parts.length >= 3) {
    const last = parts[parts.length - 1] ?? ''
    const match = /^(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})Z$/.exec(last)
    const name = parts[0] ?? session
    if (match !== null) {
      const month = MONTHS[Number(match[2]) - 1] ?? match[2]
      return `${name} · ${match[3]} ${month} ${match[4]}:${match[5]}Z`
    }
  }
  return clip(session.replace(/[-_]+/g, ' '), 40)
}

export function groupFinished(rows: readonly WorkerRow[]): WorkerGroup[] {
  const groups = new Map<string, WorkerRow[]>()
  for (const row of rows) {
    const key = row.ownerSession ?? ''
    const list = groups.get(key)
    if (list === undefined) groups.set(key, [row])
    else list.push(row)
  }

  const built: WorkerGroup[] = []
  for (const [session, list] of groups) {
    const sorted = [...list].sort(byFinishedDesc)
    const starts = sorted
      .map(row => row.startedAt ?? row.finishedAt ?? 0)
      .filter(at => at > 0)
    const ends = sorted
      .map(row => row.finishedAt ?? 0)
      .filter(at => at > 0)
    const oldest = starts.length === 0 ? 0 : Math.min(...starts)
    const newest = ends.length === 0 ? 0 : Math.max(...ends)
    built.push({
      session,
      label: sessionLabel(session === '' ? null : session),
      rows: sorted,
      spanMs: newest > oldest ? newest - oldest : 0,
    })
  }
  return built.sort(
    (a, b) =>
      (b.rows[0]?.finishedAt ?? 0) - (a.rows[0]?.finishedAt ?? 0) ||
      a.session.localeCompare(b.session),
  )
}

export function metricMaxima(rows: readonly WorkerRow[]): MetricsMaxima {
  let tools = METRIC_FLOORS.tools
  let steps = METRIC_FLOORS.steps
  let tokens = METRIC_FLOORS.tokens
  let files = METRIC_FLOORS.files
  let idle = METRIC_FLOORS.idle
  for (const row of rows) {
    if (row.metrics !== null) {
      tools = Math.max(tools, row.metrics.toolCalls)
      steps = Math.max(steps, row.metrics.modelSteps)
      tokens = Math.max(tokens, row.metrics.outputTokens)
      files = Math.max(files, row.metrics.fileWrites)
    }
    if (row.idleMs !== null && isActivePhase(row.phase)) {
      idle = Math.max(idle, row.idleMs / 60_000)
    }
  }
  return { tools, steps, tokens, files, idle }
}

export function viewOf(
  rows: WorkerRow[],
  metas: readonly StatusMeta[],
  now: number,
  root: string,
  error: string | null,
): WorkerView {
  const running = rows
    .filter(row => !isFinalPhase(row.phase))
    .sort(byStartedDesc)
  const finished = rows
    .filter(row => isFinalPhase(row.phase))
    .sort(byFinishedDesc)
  const counts: WorkerCounts = {
    running: metas.filter(meta => meta.phase === 'running').length,
    stalled: metas.filter(meta => meta.phase === 'stalled').length,
    failed: metas.filter(meta => meta.phase === 'failed').length,
    finished: metas.filter(meta => meta.phase === 'finished').length,
  }
  return {
    running,
    finished,
    finishedGroups: groupFinished(finished),
    counts,
    maxima: metricMaxima(rows),
    readAt: now,
    root,
    error,
  }
}

/**
 * The jobs still in flight, in the order the pane shows them. An unreadable
 * record (a `status.json` caught mid-write) has no phase to colour and no
 * start time to compare, so the band and the mobile summary leave it out.
 */
export function liveRows(view: WorkerView): WorkerRow[] {
  return view.running.filter(row => row.phase !== 'unreadable')
}

/**
 * The idle rule: nothing has started since the Claude session that hosts the
 * pane began. `appStartedAt` is `$.clock.now()` read in the `session.start`
 * hook and kept in `$.state` (the earliest reliable app/session start the API
 * exposes), so a fresh session starts quiet instead of replaying the last app
 * run's jobs. A job already running when the app restarted still counts (its
 * progress is live), and a mod hot-loaded into a running session never claims
 * idle: with no start time to compare, any job at all keeps the pane up.
 */
export function isIdle(
  view: WorkerView,
  appStartedAt: number | null,
): boolean {
  if (appStartedAt === null) {
    return view.running.length === 0 && view.finished.length === 0
  }
  for (const row of [...view.running, ...view.finished]) {
    const at = row.startedAt ?? row.finishedAt
    if (row.phase === 'running' || row.phase === 'stalled') {
      if (at === null || at >= appStartedAt) return false
    } else if (at !== null && at >= appStartedAt) {
      return false
    }
  }
  return true
}

/** Midnight UTC of `now`: dsh records timestamps in UTC, so "today" is UTC. */
export function dayStart(now: number): number {
  const date = new Date(now)
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate())
}

/**
 * Jobs that ended since UTC midnight: `finished` counts successes only, so a
 * cancelled run is neither a finish nor a failure.
 */
export function todayCounts(
  view: WorkerView,
  now: number,
): { finished: number; failed: number } {
  const start = dayStart(now)
  let finished = 0
  let failed = 0
  for (const row of view.finished) {
    const at = row.finishedAt ?? row.startedAt
    if (at === null || at < start) continue
    if (row.outcome === 'ok') finished += 1
    else if (row.outcome === 'failed') failed += 1
  }
  return { finished, failed }
}

/** One running row's live facts: elapsed, tool calls, idle, lease left. */
export function rowMeta(row: WorkerRow, now: number): string {
  const bits: string[] = []
  if (row.startedAt !== null) {
    bits.push(formatLive(Math.max(0, now - row.startedAt)))
  }
  if (row.metrics !== null) bits.push(`${row.metrics.toolCalls} tools`)
  const idle = idleMinutes(row)
  if (idle !== null) bits.push(`idle ${idle}m`)
  if (row.leaseMs !== null) bits.push(`lease ${formatLease(row.leaseMs)}`)
  return bits.join(' · ')
}

/**
 * `/dsh-workers`' answer where no pane can be placed (the Android app, a
 * narrow surface): a compact Markdown block, one line per live job, then the
 * day's roll-up.
 */
export function summaryText(view: WorkerView, now: number): string {
  const live = liveRows(view)
  const today = todayCounts(view, now)
  const head = `**DeepSeek workers** — ${view.counts.running} running · ${view.counts.stalled} stalled`
  const rows =
    live.length === 0
      ? ['No workers running.']
      : live.map(row => {
          const job = row.kind === 'data_job' ? ' `job`' : ''
          return `- ${phaseGlyph(row.phase)}${job} **${row.title}** — ${rowMeta(row, now)}`
        })
  return [head, '', ...rows, '', `${today.finished} finished · ${today.failed} failed today`].join('\n')
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

/** The panel's live duration: `16m 15s`, `1h 02m`, `3d 05h`. */
export function formatLive(ms: number | null): string {
  if (ms === null || !Number.isFinite(ms)) return '–'
  const seconds = Math.max(0, Math.floor(ms / 1000))
  if (seconds < 60) return `${seconds}s`
  const totalMinutes = Math.floor(seconds / 60)
  if (totalMinutes < 60) {
    return `${totalMinutes}m ${String(seconds % 60).padStart(2, '0')}s`
  }
  const hours = Math.floor(totalMinutes / 60)
  if (hours < 24) {
    return `${hours}h ${String(totalMinutes % 60).padStart(2, '0')}m`
  }
  return `${Math.floor(hours / 24)}d ${String(hours % 24).padStart(2, '0')}h`
}

export function formatAgo(ms: number | null): string {
  return ms === null ? '–' : `${formatDuration(ms)} ago`
}

export function formatTokens(tokens: number | null): string {
  if (tokens === null || !Number.isFinite(tokens) || tokens < 0) return '–'
  if (tokens < 1000) return String(Math.floor(tokens))
  if (tokens < 1_000_000) {
    const thousands = tokens / 1000
    return `${thousands >= 10 ? Math.round(thousands) : thousands.toFixed(1)}k`
  }
  const millions = tokens / 1_000_000
  return `${millions >= 10 ? Math.round(millions) : millions.toFixed(1)}M`
}

export function formatLease(ms: number | null): string {
  if (ms === null) return '–'
  return ms < 0 ? `expired ${formatDuration(-ms)}` : `${formatDuration(ms)} left`
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
      return '✓'
    case 'cancelled':
      return '⊘'
    case 'unreadable':
      return '?'
  }
}

export function phaseTone(
  phase: WorkerPhase,
): 'success' | 'warning' | 'error' | 'muted' | 'info' {
  switch (phase) {
    case 'running':
      return 'success'
    case 'stalled':
      return 'warning'
    case 'failed':
      return 'error'
    case 'finished':
      return 'info'
    case 'cancelled':
    case 'unreadable':
      return 'muted'
  }
}

export function outcomeGlyph(outcome: WorkerOutcome | null): string {
  if (outcome === 'ok') return '✓'
  if (outcome === 'failed') return '✕'
  return '⊘'
}

/** The hex a phase draws with on the dark card (chips use their own pair). */
export function phaseColor(phase: WorkerPhase): string {
  return STATUS[phaseTone(phase)].fill
}

export function outcomeColor(outcome: WorkerOutcome | null): string {
  // A finished row's dot follows the phase palette, not the theme: lime for a
  // clean finish, red for a failure, grey for cancelled (and a missing outcome).
  if (outcome === 'ok') return STATUS.info.fill
  if (outcome === 'failed') return STATUS.error.fill
  return STATUS.muted.fill
}

export function branchLabel(branch: string | null): string | null {
  if (branch === null) return null
  return clip(branch.replace(/^dsh\//, ''), 28)
}

export function idleMinutes(row: WorkerRow): number | null {
  if (!isActivePhase(row.phase) || row.idleMs === null) return null
  return Math.max(0, Math.round(row.idleMs / 60_000))
}

export function heatRatio(value: number | null, max: number): number {
  if (value === null || !Number.isFinite(value) || value <= 0) return 0
  return Math.max(0, Math.min(1, value / Math.max(1, max)))
}

/** A tiny horizontal bar: filled cells ∝ value / max. */
export function barCells(value: number, max: number, width: number): string {
  const cells = Math.max(1, Math.round(width))
  const ratio = max <= 0 ? 0 : Math.max(0, Math.min(1, value / max))
  const filled = Math.max(1, Math.round(cells * ratio))
  return `${'█'.repeat(filled)}${'░'.repeat(Math.max(0, cells - filled))}`
}

/** Sorted tool counts for the detail card's breakdown. */
export function toolBreakdown(
  metrics: WorkerMetrics | null,
  limit = 5,
): Array<{ tool: string; count: number }> {
  if (metrics === null) return []
  return Object.entries(metrics.byTool)
    .filter(([, count]) => count > 0)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([tool, count]) => ({ tool, count }))
}

