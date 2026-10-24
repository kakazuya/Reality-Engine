// Incremental scan of `<job>/result.md.events.jsonl`, the raw dsh event
// stream. Counts mirror dsh-worker's server/progress.py: only committed tool
// calls, model steps (status step_end), output tokens, recent file writes and
// the last tool are kept -- never reasoning text, tool output or commands.
//
// `$.fs.read` has no ranged form, so the engine still copies a file to reach
// it; what this module avoids is re-parsing it. The cache holds the byte
// offset consumed and the counts built so far, a read resumes at that offset,
// and only complete lines are consumed (a half-written trailing line waits
// for the next tick). Rescans read the file again only when its size changed.

import type {
  EventCounts,
  EventScan,
  ScanCache,
  WorkerMetrics,
} from '../types'

export const SPARK_BUCKETS = 30
export const SPARK_BUCKET_MS = 60_000
const RECENT_FILES = 10
const WRITE_TOOLS = new Set([
  'write',
  'edit',
  'multiedit',
  'multi_edit',
  'apply_patch',
  'notebook_edit',
])

export const EMPTY_COUNTS: EventCounts = {
  toolCalls: 0,
  modelSteps: 0,
  outputTokens: 0,
  recentFiles: [],
  lastTool: null,
  lastToolTarget: null,
  byTool: {},
}

export const EMPTY_SCAN: ScanCache = { jobs: {} }

const decoder = new TextDecoder()

function obj(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

function int(value: unknown): number {
  const number = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0
}

function copyCounts(counts: EventCounts): EventCounts {
  return {
    toolCalls: counts.toolCalls,
    modelSteps: counts.modelSteps,
    outputTokens: counts.outputTokens,
    recentFiles: [...counts.recentFiles],
    lastTool: counts.lastTool,
    lastToolTarget: counts.lastToolTarget,
    byTool: { ...counts.byTool },
  }
}

export function emptyScan(now: number): EventScan {
  return {
    ...copyCounts(EMPTY_COUNTS),
    offset: 0,
    size: 0,
    lines: 0,
    unparsedLines: 0,
    spark: Array.from({ length: SPARK_BUCKETS }, () => 0),
    sparkAt: now,
  }
}

/** Base64 -> bytes, the shape `$.fs.read(path, { as: "bytes" })` answers. */
export function decodeBase64(base64: string): Uint8Array {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

function toolInput(event: Record<string, unknown>): Record<string, unknown> {
  let raw = event['input']
  if (typeof raw === 'string') {
    try {
      raw = JSON.parse(raw) as unknown
    } catch {
      return {}
    }
  }
  return obj(raw) ?? {}
}

/** Short, non-secret target hint: a path, pattern or the tool's description. */
function toolHint(args: Record<string, unknown>): string | null {
  for (const key of ['file_path', 'path', 'notebook_path', 'pattern']) {
    const value = args[key]
    if (typeof value === 'string' && value !== '') return value.slice(0, 160)
  }
  const description = args['description']
  return typeof description === 'string' && description !== ''
    ? description.slice(0, 120)
    : null
}

function consume(counts: EventCounts, line: string): boolean {
  let event: unknown
  try {
    event = JSON.parse(line) as unknown
  } catch {
    return false
  }
  const record = obj(event)
  if (record === null) return false
  const type = record['type']

  if (type === 'tool_call') {
    const name = record['tool'] ?? record['name']
    const tool =
      typeof name === 'string' && name.trim() !== ''
        ? name.trim().slice(0, 24)
        : 'unknown'
    counts.toolCalls += 1
    counts.byTool[tool] = (counts.byTool[tool] ?? 0) + 1
    counts.lastTool = tool

    const args = toolInput(record)
    counts.lastToolTarget = toolHint(args)

    if (WRITE_TOOLS.has(tool.toLowerCase())) {
      const target =
        args['file_path'] ?? args['path'] ?? args['notebook_path']
      if (typeof target === 'string' && target !== '') {
        const path = target.slice(0, 300)
        const existing = counts.recentFiles.indexOf(path)
        if (existing >= 0) counts.recentFiles.splice(existing, 1)
        counts.recentFiles.push(path)
        if (counts.recentFiles.length > RECENT_FILES) {
          counts.recentFiles.splice(0, counts.recentFiles.length - RECENT_FILES)
        }
      }
    }
    return true
  }

  if (type === 'status') {
    if (record['phase'] === 'step_end') {
      counts.modelSteps += 1
      const usage = obj(record['usage'])
      if (usage !== null) {
        counts.outputTokens += int(
          usage['outputTokens'] ?? usage['output_tokens'],
        )
      }
    }
    return true
  }

  return true
}

/**
 * Consume every complete line at or after `offset`. A trailing partial line
 * stays unconsumed: the returned offset is the last newline + 1, so the next
 * call re-reads that line once it is complete.
 */
export function scanEvents(
  bytes: Uint8Array,
  offset: number,
  counts: EventCounts,
): { counts: EventCounts; offset: number; lines: number; unparsed: number } {
  const start = Math.max(0, Math.min(offset, bytes.length))
  const next = copyCounts(counts)
  if (start >= bytes.length) {
    return { counts: next, offset: start, lines: 0, unparsed: 0 }
  }

  let end = -1
  for (let index = bytes.length - 1; index >= start; index -= 1) {
    if (bytes[index] === 10) {
      end = index
      break
    }
  }
  if (end < start) {
    return { counts: next, offset: start, lines: 0, unparsed: 0 }
  }

  const text = decoder.decode(bytes.subarray(start, end + 1))
  let lines = 0
  let unparsed = 0
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    lines += 1
    if (!consume(next, line)) unparsed += 1
  }
  return { counts: next, offset: end + 1, lines, unparsed }
}

/** Shift the 30 one-minute buckets to `now` and add this tick's events. */
export function advanceSpark(
  spark: number[] | undefined,
  sparkAt: number | undefined,
  now: number,
  events: number,
): { spark: number[]; sparkAt: number } {
  const buckets =
    spark !== undefined && spark.length === SPARK_BUCKETS
      ? [...spark]
      : Array.from({ length: SPARK_BUCKETS }, () => 0)
  const since = sparkAt ?? now
  const shift = Math.max(0, Math.floor((now - since) / SPARK_BUCKET_MS))
  if (shift >= SPARK_BUCKETS) {
    const fresh = Array.from({ length: SPARK_BUCKETS }, () => 0)
    fresh[SPARK_BUCKETS - 1] = events
    return { spark: fresh, sparkAt: now }
  }
  if (shift > 0) {
    buckets.splice(0, shift)
    for (let index = 0; index < shift; index += 1) buckets.push(0)
  }
  buckets[SPARK_BUCKETS - 1] = (buckets[SPARK_BUCKETS - 1] ?? 0) + events
  // Keep the bucket boundary, do not reset it to `now`: a 15 s refresh would
  // otherwise always see a zero-minute delta and the window would never move.
  return { spark: buckets, sparkAt: since + shift * SPARK_BUCKET_MS }
}

/**
 * The cache update for one read: resume at the stored byte offset, reset on a
 * shorter (truncated or replaced) file, keep the counts otherwise.
 */
export function resumeEvents(
  previous: EventScan | undefined,
  bytes: Uint8Array,
  now: number,
): EventScan {
  const base = previous ?? emptyScan(now)
  const reset = bytes.length < base.offset || bytes.length < base.size
  const scanned = scanEvents(
    bytes,
    reset ? 0 : base.offset,
    reset ? EMPTY_COUNTS : base,
  )
  const spark = advanceSpark(
    reset ? undefined : base.spark,
    reset ? undefined : base.sparkAt,
    now,
    previous !== undefined && !reset ? scanned.lines : 0,
  )
  return {
    ...scanned.counts,
    offset: scanned.offset,
    size: bytes.length,
    lines: (reset ? 0 : base.lines) + scanned.lines,
    unparsedLines: (reset ? 0 : base.unparsedLines) + scanned.unparsed,
    spark: spark.spark,
    sparkAt: spark.sparkAt,
  }
}

/** No read this tick (size unchanged): only the sparkline window moves. */
export function touchEvents(previous: EventScan, now: number): EventScan {
  const spark = advanceSpark(previous.spark, previous.sparkAt, now, 0)
  return { ...previous, spark: spark.spark, sparkAt: spark.sparkAt }
}

export function metricsOf(scan: EventScan): WorkerMetrics {
  return {
    toolCalls: scan.toolCalls,
    modelSteps: scan.modelSteps,
    outputTokens: scan.outputTokens,
    fileWrites: scan.recentFiles.length,
    lastTool: scan.lastTool,
    lastToolTarget: scan.lastToolTarget,
    byTool: { ...scan.byTool },
  }
}

export function pruneScans(
  cache: ScanCache,
  keepIds: ReadonlySet<string>,
): ScanCache {
  const jobs: Record<string, EventScan> = {}
  for (const [id, scan] of Object.entries(cache.jobs)) {
    if (keepIds.has(id)) jobs[id] = scan
  }
  return { jobs }
}
