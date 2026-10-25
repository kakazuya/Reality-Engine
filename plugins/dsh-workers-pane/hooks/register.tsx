import { atom, read as readState, update as updateState } from 'claude-code'
import type {
  BoxProps,
  ButtonProps,
  ElementConstructor,
  EngineInterface,
  PluginOptions,
  Register,
  SvgProps,
  TextProps,
} from 'claude-code'

import type {
  ActivityLine,
  EventScan,
  ScanCache,
  WorkerRow,
  WorkerView,
} from '../types'
import {
  EMPTY_SCAN,
  decodeBase64,
  metricsOf,
  pruneScans,
  resumeEvents,
  touchEvents,
} from './events'
import { C, STATUS, heatColor, leasePalette, mixHex } from './palette'
import {
  EMPTY_VIEW,
  barCells,
  branchLabel,
  clip,
  failedStartMeta,
  formatAgo,
  formatDuration,
  formatLease,
  formatLive,
  formatTokens,
  heatRatio,
  idleMinutes,
  isActivePhase,
  isFinalPhase,
  isIdle,
  leaseFraction,
  leaseTone,
  liveRows,
  outcomeColor,
  outcomeGlyph,
  phaseColor,
  phaseGlyph,
  resultTailOf,
  rowMeta,
  rowOf,
  sessionLabel,
  statusMeta,
  summaryText,
  toolBreakdown,
  viewOf,
} from './rows'
import type { StatusMeta } from './rows'

const PANE = 'dsh-workers'
const COMMAND = 'dsh-workers'
const TITLE = 'DeepSeek workers'
const REFRESH_MS = 15_000
// Names are timestamps, so the newest dirs are the newest jobs. The runtime
// keeps every session's jobs here; 200 covers a long-lived fleet while keeping
// the per-tick status reads bounded.
// ponytail: fixed 200-dir window; make it userConfig if older jobs matter.
const SCAN_LIMIT = 200
const DEFAULT_ROOT =
  'C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/dsh-worker/runtime/jobs'

const view = atom({ plugin: 'dsh-workers', key: 'view' } as const, EMPTY_VIEW)
const scan = atom({ plugin: 'dsh-workers', key: 'scan' } as const, EMPTY_SCAN)
const expandedId = atom(
  { plugin: 'dsh-workers', key: 'expandedId' } as const,
  null as string | null,
)
const finishedOpen = atom(
  { plugin: 'dsh-workers', key: 'finishedOpen' } as const,
  false,
)
// `$.clock.now()` read in the `session.start` hook: the earliest reliable
// app/session start the API exposes. `$.state` (not a module variable) so a
// hot reload keeps it; kept per session, never in `$.store`, so an app restart
// starts a fresh quiet window instead of replaying the last run's jobs.
const startedAt = atom(
  { plugin: 'dsh-workers', key: 'startedAt' } as const,
  null as number | null,
)

let isRefreshing = false
let timer: { cancel: () => void } | null = null

type PaneKit = {
  Box: ElementConstructor<BoxProps>
  Text: ElementConstructor<TextProps>
  Button: ElementConstructor<ButtonProps>
  Svg: ElementConstructor<SvgProps> | null
}

type PaneProps = {
  kit: PaneKit
  view: WorkerView
  expandedId: string | null
  finishedOpen: boolean
  now: number
  width: number
  onToggleRow: (id: string) => Promise<void>
  onToggleFinished: () => Promise<void>
}

// --------------------------------------------------------------------- IO

function rootOf($: EngineInterface, options: PluginOptions): string {
  const configured =
    typeof options['jobsRoot'] === 'string' && options['jobsRoot'].trim() !== ''
      ? options['jobsRoot'].trim()
      : DEFAULT_ROOT
  const isAbsolute =
    /^[A-Za-z]:[\\/]/.test(configured) ||
    configured.startsWith('/') ||
    configured.startsWith('\\\\')
  const root = isAbsolute
    ? configured
    : `${$.plugin.root.replace(/[\\/]+$/, '')}/${configured.replace(
        /^\.?[\\/]+/,
        '',
      )}`
  return root.replace(/[\\/]+$/, '')
}

async function readText(
  $: EngineInterface,
  path: string,
): Promise<string | null> {
  try {
    return await $.fs.read(path)
  } catch {
    return null
  }
}

async function readJson(
  $: EngineInterface,
  path: string,
): Promise<unknown> {
  const text = await readText($, path)
  if (text === null) return null
  try {
    return JSON.parse(text) as unknown
  } catch {
    return null
  }
}

async function readBytes(
  $: EngineInterface,
  path: string,
): Promise<Uint8Array | null> {
  try {
    const answer = await $.fs.read(path, { as: 'bytes' })
    return decodeBase64(answer.base64)
  } catch {
    return null
  }
}

function jobPath(root: string, id: string, name: string): string {
  return `${root}/${id}/${name}`
}

async function readLogMtime(
  $: EngineInterface,
  root: string,
  id: string,
): Promise<number | null> {
  const found = await Promise.all(
    ['stdout.log', 'stderr.log'].map(async name => {
      try {
        return (await $.fs.stat(jobPath(root, id, name))).mtimeMs
      } catch {
        return null
      }
    }),
  )
  const times = found.filter((time): time is number => time !== null)
  return times.length === 0 ? null : Math.max(...times)
}

/**
 * Resume the event counts for one job. A read happens only when its size
 * changed; the byte offset in the cache means only the new tail is parsed.
 */
async function scanEventsFile(
  $: EngineInterface,
  root: string,
  id: string,
  previous: EventScan | undefined,
  now: number,
): Promise<EventScan | null> {
  const path = jobPath(root, id, 'result.md.events.jsonl')
  let size: number
  try {
    size = (await $.fs.stat(path)).size
  } catch {
    return null
  }
  if (previous !== undefined && previous.size === size) {
    return touchEvents(previous, now)
  }
  const bytes = await readBytes($, path)
  if (bytes === null) {
    return previous === undefined ? null : touchEvents(previous, now)
  }
  return resumeEvents(previous, bytes, now)
}

type Prepared = {
  id: string
  status: unknown
  meta: StatusMeta
  job: unknown
  logMtimeMs: number | null
}

type Built = { row: WorkerRow; scan: EventScan | null }

async function readView(
  $: EngineInterface,
  root: string,
  now: number,
  previousScan: ScanCache,
  previousView: WorkerView,
  openId: string | null,
  openFinished: boolean,
): Promise<{ view: WorkerView; scan: ScanCache }> {
  const entries = await $.fs.list(root)
  const ids = entries
    .filter(entry => entry.kind === 'dir')
    .map(entry => entry.name)
    .sort()
    .reverse()
    .slice(0, SCAN_LIMIT)

  const statuses = await Promise.all(
    ids.map(id => readJson($, jobPath(root, id, 'status.json'))),
  )

  // A failed start has a job.json and no status.json: show it as failed
  // instead of leaving an unreadable row at the top of the pane forever.
  const prepared: Prepared[] = await Promise.all(
    ids.map(async (id, index) => {
      const status = statuses[index] ?? null
      let meta = statusMeta(id, status, now)
      let job: unknown = null
      let logMtimeMs: number | null = null
      if (meta.phase === 'unreadable') {
        job = await readJson($, jobPath(root, id, 'job.json'))
        meta = failedStartMeta(meta, job)
      } else if (meta.kind === 'data_job' && isActivePhase(meta.phase)) {
        logMtimeMs = await readLogMtime($, root, id)
        meta = statusMeta(id, status, now, logMtimeMs)
      }
      return { id, status, meta, job, logMtimeMs }
    }),
  )

  const metas = prepared.map(item => item.meta)
  const cachedFinished = new Map(
    previousView.finished.map(row => [row.id, row]),
  )

  const built: Built[] = await Promise.all(
    prepared.map(async item => {
      const { id, status, meta, logMtimeMs } = item
      const final = isFinalPhase(meta.phase)
      const cached = final ? cachedFinished.get(id) : undefined
      // A running row's card is always in view; a finished row's card only
      // exists while the finished list is open.
      const wantsDetail = openId === id && (!final || openFinished)
      const needsScan = isActivePhase(meta.phase) || (wantsDetail && final)
      const scanned = needsScan
        ? await scanEventsFile($, root, id, previousScan.jobs[id], now)
        : null

      if (cached !== undefined) {
        let row = cached
        if (needsScan && scanned !== null) {
          row = {
            ...row,
            metrics: metricsOf(scanned),
            spark: scanned.spark,
          }
        }
        if (wantsDetail && row.resultTail.length === 0) {
          const text = await readText($, jobPath(root, id, 'result.md'))
          row = { ...row, resultTail: resultTailOf(text) }
        }
        return { row, scan: scanned }
      }

      const workerActive = isActivePhase(meta.phase) && meta.kind === 'worker'
      const [job, heartbeat, brief, resultText] = await Promise.all([
        item.job !== null
          ? Promise.resolve(item.job)
          : readJson($, jobPath(root, id, 'job.json')),
        workerActive
          ? readJson($, jobPath(root, id, 'heartbeat.json'))
          : Promise.resolve(null),
        workerActive
          ? readText($, jobPath(root, id, 'brief.md'))
          : Promise.resolve(null),
        wantsDetail
          ? readText($, jobPath(root, id, 'result.md'))
          : Promise.resolve(null),
      ])

      const metrics = scanned === null ? null : metricsOf(scanned)
      const row = rowOf(id, status, job, heartbeat, brief, now, logMtimeMs, {
        meta,
        metrics,
        spark: scanned?.spark ?? null,
        resultTail: resultTailOf(resultText),
      })
      return { row, scan: scanned }
    }),
  )

  const jobs: Record<string, EventScan> = {}
  for (const item of built) {
    const entry = item.scan ?? previousScan.jobs[item.row.id]
    if (entry !== undefined) jobs[item.row.id] = entry
  }
  const nextScan = pruneScans({ jobs }, new Set(ids))
  const rows = built.map(item => item.row)
  return { view: viewOf(rows, metas, now, root, null), scan: nextScan }
}

function describe(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

/** A hook's own log line; logging itself can never throw the hook out. */
function log($: EngineInterface, message: string): void {
  try {
    $.ui.log(`dsh-workers: ${message}`, { to: 'debug' })
  } catch {
    // The debug log is a nicety too.
  }
}

/**
 * The pinned line follows the idle rule: nothing started since the session
 * began means no line at all. Stale reads say so and keep the last numbers.
 */
function setStatus(
  $: EngineInterface,
  current: WorkerView,
  appStartedAt: number | null,
): void {
  try {
    if (isIdle(current, appStartedAt)) {
      $.ui.status(undefined)
      return
    }
    const stale = current.error === null ? '' : ' · stale'
    $.ui.status(
      `dsh: ${current.counts.running} running, ${current.counts.stalled} stalled${stale}`,
    )
  } catch {
    // A status line is a nicety; the pane must still draw without one.
  }
}

async function refresh(
  $: EngineInterface,
  options: PluginOptions,
): Promise<void> {
  if (isRefreshing) return
  isRefreshing = true
  const root = rootOf($, options)
  let now = Date.now()

  try {
    now = await $.clock.now()
    const [previousView, previousScan, openId, openFinished, appStartedAt] =
      await Promise.all([
        readState($, view),
        readState($, scan),
        readState($, expandedId),
        readState($, finishedOpen),
        readState($, startedAt),
      ])
    const next = await readView(
      $,
      root,
      now,
      previousScan ?? EMPTY_SCAN,
      previousView ?? EMPTY_VIEW,
      openId ?? null,
      openFinished ?? false,
    )
    await updateState($, scan, () => next.scan)
    const stored = await updateState($, view, () => next.view)
    setStatus($, stored, appStartedAt ?? null)
  } catch (error) {
    // One bad record or an IO error never escapes a hook: the last good view
    // stays on screen, the pane names the failure, and the next tick retries.
    const reason = describe(error)
    log($, `refresh failed: ${reason}`)
    try {
      const appStartedAt = (await readState($, startedAt)) ?? null
      const stored = await updateState($, view, previous => ({
        ...(previous ?? EMPTY_VIEW),
        readAt: now,
        root,
        error: `cannot read ${root}: ${reason}`,
      }))
      setStatus($, stored, appStartedAt)
    } catch {
      // Nothing left to draw from; the previous state is already on screen.
    }
  } finally {
    isRefreshing = false
  }
}

// ---------------------------------------------------------------- drawing

function pad(value: string, length: number): string {
  return value.length >= length ? value : value + ' '.repeat(length - value.length)
}

function escId(id: string): string {
  return id.replace(/[^A-Za-z0-9_-]/g, '')
}

function leaseSvg(
  fraction: number | null,
  tone: 'success' | 'warning' | 'error',
  cells: number,
  id: string,
): string {
  const width = cells * 7
  const height = 9
  const filled =
    fraction === null
      ? 0
      : Math.max(fraction > 0 ? 2 : 0, Math.round(fraction * width))
  const palette = leasePalette(tone)
  const gradient = `lease-${escId(id)}`
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<defs><linearGradient id="${gradient}" x1="0" y1="0" x2="1" y2="0">`,
    `<stop offset="0" stop-color="${palette.light}"/>`,
    `<stop offset="1" stop-color="${palette.fill}"/>`,
    `</linearGradient></defs>`,
    `<rect x="0" y="0" width="${width}" height="${height}" rx="${height / 2}" fill="${C.leaseTrack}"/>`,
    `<rect x="0" y="0" width="${filled}" height="${height}" rx="${height / 2}" fill="url(#${gradient})"/>`,
    `</svg>`,
  ].join('')
}

function sparkSvg(
  values: readonly number[],
  width: number,
  height: number,
  id: string,
): string {
  const max = Math.max(1, ...values)
  const barWidth = width / Math.max(1, values.length)
  const gradient = `spark-${escId(id)}`
  const bars = values
    .map((value, index) => {
      if (value <= 0) return ''
      const barHeight = Math.max(1, (value / max) * (height - 2))
      return `<rect x="${(index * barWidth).toFixed(1)}" y="${(height - barHeight).toFixed(1)}" width="${Math.max(1, barWidth - 1).toFixed(1)}" height="${barHeight.toFixed(1)}" rx="0.5" fill="url(#${gradient})"/>`
    })
    .join('')
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`,
    `<defs><linearGradient id="${gradient}" x1="0" y1="1" x2="0" y2="0">`,
    `<stop offset="0" stop-color="${C.spark}"/>`,
    `<stop offset="1" stop-color="${C.sparkTop}"/>`,
    `</linearGradient></defs>`,
    bars,
    `</svg>`,
  ].join('')
}

function sparkGlyphs(values: readonly number[]): string {
  const ramp = ['▁', '▂', '▃', '▄', '▅', '▆', '▇', '█']
  const max = Math.max(1, ...values)
  return values
    .map(value => {
      if (value <= 0) return '·'
      const index = Math.min(
        ramp.length - 1,
        Math.max(0, Math.ceil((value / max) * ramp.length) - 1),
      )
      return ramp[index] ?? '·'
    })
    .join('')
}

/**
 * One cell per measured job: each phase segment runs from its bright stop to
 * its deep stop, so the mix bar is the phase gradient, not flat swatches.
 */
function mixCells(
  counts: WorkerView['counts'],
  cells: number,
): Array<{ key: string; color: string }> {
  const parts = [
    {
      key: 'running',
      value: counts.running,
      light: STATUS.success.light,
      deep: STATUS.success.deep,
    },
    {
      key: 'stalled',
      value: counts.stalled,
      light: STATUS.warning.light,
      deep: STATUS.warning.deep,
    },
    {
      key: 'failed',
      value: counts.failed,
      light: STATUS.error.light,
      deep: STATUS.error.deep,
    },
    {
      key: 'cancelled',
      value: counts.cancelled,
      light: STATUS.muted.light,
      deep: STATUS.muted.deep,
    },
    {
      key: 'finished',
      value: counts.finished,
      light: STATUS.info.light,
      deep: STATUS.info.deep,
    },
  ]
  const total = parts.reduce((sum, part) => sum + part.value, 0)
  if (total <= 0) {
    return Array.from({ length: cells }, (_, index) => ({
      key: `empty-${index}`,
      color: C.track,
    }))
  }

  const used = parts.map(part =>
    part.value <= 0
      ? 0
      : Math.max(1, Math.round((part.value / total) * cells)),
  )
  let sum = used.reduce((a, b) => a + b, 0)
  for (let index = 0; sum < cells; index = (index + 1) % parts.length) {
    if (parts[index]?.value === 0) continue
    used[index] = (used[index] ?? 0) + 1
    sum += 1
  }
  while (sum > cells) {
    const biggest = used.indexOf(Math.max(...used))
    if ((used[biggest] ?? 0) <= 1) break
    used[biggest] = (used[biggest] ?? 0) - 1
    sum -= 1
  }

  const mix: Array<{ key: string; color: string }> = []
  parts.forEach((part, partIndex) => {
    const count = used[partIndex] ?? 0
    for (let index = 0; index < count; index += 1) {
      mix.push({
        key: `${part.key}-${index}`,
        color: mixHex(part.light, part.deep, count <= 1 ? 1 : index / (count - 1)),
      })
    }
  })
  return mix
}

function Divider(props: PaneProps) {
  const { Text } = props.kit
  return (
    <Text color={C.cardEdge}>{'─'.repeat(Math.max(4, props.width))}</Text>
  )
}

function HeaderCard(props: PaneProps) {
  const { Box, Text } = props.kit
  const counts = props.view.counts
  const chips = [
    {
      key: 'running',
      glyph: '●',
      label: 'running',
      value: counts.running,
      tone: STATUS.success,
    },
    {
      key: 'stalled',
      glyph: '◐',
      label: 'stalled',
      value: counts.stalled,
      tone: STATUS.warning,
    },
    {
      key: 'failed',
      glyph: '✕',
      label: 'failed',
      value: counts.failed,
      tone: STATUS.error,
    },
    {
      key: 'cancelled',
      glyph: '⊘',
      label: 'cancelled',
      value: counts.cancelled,
      tone: STATUS.muted,
    },
    {
      key: 'finished',
      glyph: '✓',
      label: 'finished',
      value: counts.finished,
      tone: STATUS.info,
    },
  ].filter(chip => chip.key !== 'cancelled' || chip.value > 0)
  const mix = mixCells(counts, Math.max(8, props.width - 2))

  return (
    <Box
      width={props.width}
      flexDirection="column"
      borderStyle="round"
      borderColor={C.cardEdge}
      backgroundColor={C.card}
    >
      <Box
        flexDirection="row"
        backgroundColor={C.headerTop}
        paddingX={1}
      >
        <Text bold color={C.title}>
          {TITLE}
        </Text>
        <Box flexGrow={1} />
        <Text color={C.subtitle}>read-only</Text>
      </Box>
      <Box
        flexDirection="row"
        flexWrap="wrap"
        columnGap={1}
        backgroundColor={C.headerMid}
        paddingX={1}
      >
        {chips.map(chip => (
          <Text
            key={chip.key}
            bold
            backgroundColor={chip.value > 0 ? chip.tone.bg : C.axis}
            color={chip.value > 0 ? chip.tone.fg : C.cardTitle}
          >
            {`${chip.glyph} ${chip.value} ${chip.label}`}
          </Text>
        ))}
      </Box>
      <Box
        flexDirection="row"
        backgroundColor={C.headerLow}
      >
        {mix.map(cell => (
          <Text key={cell.key} backgroundColor={cell.color}>
            {' '}
          </Text>
        ))}
      </Box>
    </Box>
  )
}

function RunningRow(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text, Button } = props.kit
  const { row } = props
  const live =
    row.startedAt === null ? null : Math.max(0, props.now - row.startedAt)
  const duration = formatLive(live)
  const job = row.kind === 'data_job'
  const jobCells = job ? 5 : 0
  const titleCells = Math.max(
    6,
    props.width - 2 - jobCells - duration.length - 1,
  )
  const title = clip(row.title, titleCells)
  const used = 1 + jobCells + 1 + title.length + duration.length
  const spacer = Math.max(1, props.width - used)
  const expanded = props.expandedId === row.id

  return (
    <Box
      width={props.width}
      flexDirection="column"
      backgroundColor={expanded ? C.card : undefined}
    >
      <Button key={row.id} plain onPress={() => props.onToggleRow(row.id)}>
        <Text bold color={phaseColor(row.phase)}>
          {phaseGlyph(row.phase)}
        </Text>
        {job && (
          <Text backgroundColor={C.job} color={C.jobFg} bold>
            {' job '}
          </Text>
        )}
        <Text bold>{` ${title}`}</Text>
        <Text>{' '.repeat(spacer)}</Text>
        <Text bold tabular>
          {duration}
        </Text>
      </Button>
    </Box>
  )
}

function FinishedRow(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text, Button } = props.kit
  const { row } = props
  const duration = formatLive(row.elapsedMs)
  const job = row.kind === 'data_job'
  const jobCells = job ? 5 : 0
  const exit =
    job && row.exitCode !== null ? `exit ${row.exitCode}` : ''
  const branch = branchLabel(row.branch)
  const branchText =
    branch !== null && props.width >= 60 ? ` ⎇ ${branch}` : ''
  const chevron = row.id === props.expandedId ? '⌄' : '›'
  const titleCells = Math.max(
    6,
    props.width -
      5 -
      jobCells -
      duration.length -
      branchText.length -
      (exit === '' ? 0 : exit.length + 1),
  )
  const title = clip(row.title, titleCells)
  const used =
    1 +
    jobCells +
    1 +
    title.length +
    branchText.length +
    (exit === '' ? 0 : exit.length + 1) +
    duration.length +
    2
  const spacer = Math.max(1, props.width - used)

  return (
    <Button key={row.id} plain onPress={() => props.onToggleRow(row.id)}>
      <Text bold color={outcomeColor(row.outcome)}>
        {outcomeGlyph(row.outcome)}
      </Text>
      {job && (
        <Text backgroundColor={C.job} color={C.jobFg} bold>
          {' job '}
        </Text>
      )}
      <Text>{` ${title}`}</Text>
      {exit === '' ? null : <Text dimColor>{` ${exit}`}</Text>}
      {branchText === '' ? null : (
        <Text color={C.branch}>{branchText}</Text>
      )}
      <Text>{' '.repeat(spacer)}</Text>
      <Text tabular>{duration}</Text>
      <Text color={C.subtitle}>{` ${chevron}`}</Text>
    </Button>
  )
}

function LeaseMeter(props: {
  kit: PaneKit
  row: WorkerRow
  fraction: number | null
  tone: 'success' | 'warning' | 'error'
}) {
  const { Text } = props.kit
  const Svg = props.kit.Svg
  const cells = 12
  if (Svg === null) {
    const fraction = props.fraction ?? 0
    const filled = Math.max(
      fraction > 0 ? 1 : 0,
      Math.round(cells * fraction),
    )
    return (
      <Text>
        <Text color={leasePalette(props.tone).fill}>
          {'█'.repeat(filled)}
        </Text>
        <Text color={C.leaseTrack}>{'░'.repeat(cells - filled)}</Text>
      </Text>
    )
  }
  return (
    <Svg
      source={leaseSvg(props.fraction, props.tone, cells, props.row.id)}
      alt={`lease remaining ${formatLease(props.row.leaseMs)}`}
      width={cells * 7}
      height={9}
    />
  )
}

function LeaseRow(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text } = props.kit
  const { row } = props
  const fraction = leaseFraction(row.leaseMs, row.leaseTotalMs)
  const tone = leaseTone(fraction, row.leaseMs)
  return (
    <Box flexDirection="row" alignItems="center" marginTop={1}>
      <Text color={C.subtitle} size="caption">
        {'lease '}
      </Text>
      <LeaseMeter
        kit={props.kit}
        row={row}
        fraction={fraction}
        tone={tone}
      />
      <Text bold color={tone}>
        {` ${formatLease(row.leaseMs)}`}
      </Text>
    </Box>
  )
}

function SparkRow(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text } = props.kit
  const row = props.row
  const values = (row.spark ?? []).slice(-30)
  if (values.length === 0 || !values.some(value => value > 0)) return null
  const Svg = props.kit.Svg
  return (
    <Box flexDirection="row" alignItems="center" marginTop={1}>
      <Text color={C.subtitle} size="caption">
        {'activity 30m '}
      </Text>
      {Svg === null ? (
        <Text color={C.spark}>{sparkGlyphs(values)}</Text>
      ) : (
        <Svg
          source={sparkSvg(values, 90, 16, row.id)}
          alt="events per minute, last 30 minutes"
          width={90}
          height={16}
        />
      )}
    </Box>
  )
}

function OutputArea(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text } = props.kit
  const { row } = props
  const lines: ActivityLine[] =
    row.activity.length > 0
      ? row.activity.slice(-8)
      : row.resultTail.slice(-8).map(text => ({ time: '', text }))
  if (lines.length === 0) {
    return <Text dimColor>No output yet</Text>
  }
  const room = Math.max(20, props.width - 8)
  return (
    <Box flexDirection="column">
      {lines.map((line, index) => (
        <Text key={`${index}-${line.time}`} wrap="truncate-end">
          {line.time === '' ? null : (
            <Text dimColor>{`${line.time} `}</Text>
          )}
          {clip(line.text, room)}
        </Text>
      ))}
    </Box>
  )
}

function MetricStrip(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text } = props.kit
  const { row } = props
  const metrics = row.metrics
  const idle = idleMinutes(row)
  const tiles = [
    {
      key: 'tools',
      label: 'tools',
      value: metrics?.toolCalls ?? null,
      max: props.view.maxima.tools,
      display: metrics === null ? '–' : String(metrics.toolCalls),
    },
    {
      key: 'steps',
      label: 'steps',
      value: metrics?.modelSteps ?? null,
      max: props.view.maxima.steps,
      display: metrics === null ? '–' : String(metrics.modelSteps),
    },
    {
      key: 'tokens',
      label: 'tokens',
      value: metrics?.outputTokens ?? null,
      max: props.view.maxima.tokens,
      display: metrics === null ? '–' : formatTokens(metrics.outputTokens),
    },
    {
      key: 'files',
      label: 'files',
      value: metrics?.fileWrites ?? null,
      max: props.view.maxima.files,
      display: metrics === null ? '–' : String(metrics.fileWrites),
    },
    {
      key: 'idle',
      label: 'idle m',
      value: idle,
      max: props.view.maxima.idle,
      display: idle === null ? '–' : String(idle),
    },
  ]
  return (
    <Box
      flexDirection="row"
      flexWrap="wrap"
      columnGap={1}
      marginTop={1}
    >
      {tiles.map(tile => (
        <Box
          key={tile.key}
          width={10}
          flexDirection="column"
          backgroundColor={heatColor(heatRatio(tile.value, tile.max))}
          paddingX={1}
        >
          <Text bold tabular color={C.heatFg}>
            {tile.display}
          </Text>
          <Text size="caption" color={C.heatFg}>
            {tile.label}
          </Text>
        </Box>
      ))}
    </Box>
  )
}

function ToolBars(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text } = props.kit
  const tools = toolBreakdown(props.row.metrics)
  if (tools.length === 0) return null
  const max = tools[0]?.count ?? 1
  return (
    <Box flexDirection="column" marginTop={1}>
      <Text color={C.subtitle} size="caption">
        TOOLS
      </Text>
      {tools.map(tool => (
        <Box key={tool.tool} flexDirection="row">
          <Text mono dimColor>
            {pad(clip(tool.tool, 12), 12)}
          </Text>
          <Text color={C.bar}>{barCells(tool.count, max, 10)}</Text>
          <Text bold>{` ${tool.count}`}</Text>
        </Box>
      ))}
    </Box>
  )
}

function DetailCard(props: PaneProps & { row: WorkerRow }) {
  const { Box, Text } = props.kit
  const { row } = props
  const room = Math.max(20, props.width - 8)
  const lastTool = row.metrics?.lastTool ?? null
  const target = row.metrics?.lastToolTarget ?? null

  return (
    <Box
      width={props.width}
      marginTop={1}
      marginBottom={1}
      flexDirection="column"
      borderStyle="round"
      borderColor={phaseColor(row.phase)}
      backgroundColor={C.card}
      paddingX={1}
    >
      <Box
        flexDirection="column"
        borderStyle="round"
        borderColor={C.axis}
        backgroundColor="#0a0f1d"
        paddingX={1}
      >
        {row.briefLines.length === 0 ? (
          <Text mono dimColor>
            no brief
          </Text>
        ) : (
          row.briefLines.map((line, index) => (
            <Text
              key={String(index)}
              mono
              color={C.result}
              wrap="truncate-end"
            >
              {clip(line, room)}
            </Text>
          ))
        )}
      </Box>

      <Box marginTop={1} flexDirection="column">
        <Text color={C.subtitle} size="caption">
          OUTPUT
        </Text>
        <OutputArea {...props} />
      </Box>

      {row.kind === 'worker' && <MetricStrip {...props} />}

      {isActivePhase(row.phase) && row.leaseMs !== null && (
        <LeaseRow {...props} />
      )}

      <SparkRow {...props} />

      {lastTool !== null && (
        <Box marginTop={1}>
          <Text wrap="truncate-end">
            <Text color={C.subtitle} size="caption">
              {'last tool '}
            </Text>
            <Text bold color="suggestion">
              {lastTool}
            </Text>
            {target === null ? null : (
              <Text dimColor>{` → ${clip(target, 60)}`}</Text>
            )}
          </Text>
        </Box>
      )}

      <ToolBars {...props} />

      <Box flexDirection="column" marginTop={1}>
        {row.branch !== null && (
          <Text color={C.branch} wrap="truncate-end">
            {`⎇ ${clip(row.branch, room)}`}
          </Text>
        )}
        {row.workspace !== null && (
          <Text dimColor wrap="truncate-end">
            {`workspace ${clip(row.workspace, room)}`}
          </Text>
        )}
        <Text dimColor wrap="truncate-end">
          {`session ${sessionLabel(row.ownerSession)}`}
        </Text>
        {row.exitCode !== null && (
          <Text dimColor>{`exit ${row.exitCode}`}</Text>
        )}
        {isFinalPhase(row.phase) && row.finishedAt !== null && (
          <Text dimColor>{`ended ${formatAgo(props.now - row.finishedAt)}`}</Text>
        )}
      </Box>
    </Box>
  )
}

function FinishedSection(props: PaneProps) {
  const { Box, Text, Button } = props.kit
  const open = props.finishedOpen
  const count = props.view.finished.length
  return (
    <Box flexDirection="column" marginTop={1}>
      <Button
        key="finished"
        plain
        dimColor
        onPress={props.onToggleFinished}
      >
        {`Finished ${count} ${open ? '▾' : '▸'}`}
      </Button>
      {open && count === 0 && <Text dimColor>No finished jobs</Text>}
      {open &&
        props.view.finishedGroups.map(group => (
          <Box
            key={group.session === '' ? 'unknown-session' : group.session}
            flexDirection="column"
            marginTop={1}
          >
            <Box flexDirection="row">
              <Text dimColor>
                {group.label}
                {` · ${group.rows.length}`}
              </Text>
              <Box flexGrow={1} />
              <Text dimColor>{formatDuration(group.spanMs)}</Text>
            </Box>
            {group.rows.map((row, index) => (
              <Box key={row.id} flexDirection="column">
                {index > 0 && <Divider {...props} />}
                <FinishedRow {...props} row={row} />
                {props.expandedId === row.id && (
                  <DetailCard {...props} row={row} />
                )}
              </Box>
            ))}
          </Box>
        ))}
    </Box>
  )
}

function PaneTree(props: PaneProps) {
  const { Box, Text } = props.kit
  const { view: current } = props
  return (
    <Box flexDirection="column" width={props.width}>
      <HeaderCard {...props} />
      {current.error !== null && (
        <Text color="error" wrap="truncate-end">
          {current.error}
        </Text>
      )}
      {current.error === null &&
        current.running.length === 0 &&
        current.finished.length === 0 && (
          <Text dimColor wrap="truncate-end">
            {`No jobs in ${current.root}`}
          </Text>
        )}

      <Box flexDirection="row" marginTop={1}>
        <Text dimColor>Running</Text>
        <Text dimColor>{` ${current.running.length}`}</Text>
      </Box>
      {current.running.length === 0 && current.error === null && (
        <Text dimColor>No workers running</Text>
      )}
      {current.running.map((row, index) => (
        <Box key={row.id} flexDirection="column">
          {index > 0 && <Divider {...props} />}
          <RunningRow {...props} row={row} />
          {props.expandedId === row.id && <DetailCard {...props} row={row} />}
        </Box>
      ))}

      <FinishedSection {...props} />

      <Box marginTop={1}>
        <Text dimColor wrap="truncate-end">
          {`updated ${formatDuration(props.now - current.readAt)} ago · every 15s`}
        </Text>
      </Box>
    </Box>
  )
}

// ------------------------------------------------------------------ wiring

function startTimer($: EngineInterface, options: PluginOptions): void {
  timer?.cancel()
  timer = $.clock.every(REFRESH_MS, () => {
    void refresh($, options).catch(() => undefined)
  })
}

/**
 * A hot reload drops the module's timers with the old environment, and a mod
 * hot-loaded into a running session never saw `session.start`: the next event
 * that reaches the module re-arms the 15 s tick.
 */
function ensureTimer($: EngineInterface, options: PluginOptions): void {
  if (timer === null) startTimer($, options)
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    try {
      await $.command.register({
        name: COMMAND,
        description: 'Show DeepSeek worker jobs in a pane',
      })
      const now = await $.clock.now()
      // The earliest reliable app/session start the API exposes: this hook's
      // own time, kept in `$.state` so a hot reload keeps the same window.
      await updateState($, startedAt, previous => previous ?? now)
      startTimer($, options)
      await refresh($, options)

      const appStartedAt = (await readState($, startedAt)) ?? null
      const current = (await readState($, view)) ?? EMPTY_VIEW
      if (!isIdle(current, appStartedAt)) {
        void $.ui.open({ id: PANE, title: TITLE }).catch(() => undefined)
      }
    } catch (error) {
      log($, `session.start failed: ${describe(error)}`)
    }

    return next(e)
  })

  on('command.run', { command: COMMAND }, async $ => {
    await refresh($, options)
    // A mod hot-loaded into a running session never saw session.start.
    ensureTimer($, options)

    let isPlaced = false
    try {
      isPlaced = (await $.ui.open({ id: PANE, title: TITLE })).isPlaced
    } catch {
      // A surface that refuses the pane (or a hook above) still gets the text.
    }
    if (isPlaced) return { text: `${TITLE} pane opened.` }

    // No pane can be placed here (the Android app, a narrow surface): answer
    // with what the pane would have shown, as command output.
    const current = (await readState($, view)) ?? EMPTY_VIEW
    return { text: summaryText(current, await $.clock.now()) }
  }).catch(async ($, e, next) => {
    if (next.called) return next(e)
    log($, `command.run ${e.command}: hook failed; the debug log has the reason`)

    return { text: `${TITLE}: jobs could not be read. Try again.` }
  })

  on('session.end', async ($, e, next) => {
    // A /clear (or a resume) ends the conversation, not the process: there is
    // no new session.start, so the tick and the pinned line must survive it.
    if (e.reason !== 'clear' && e.reason !== 'resume') {
      timer?.cancel()
      timer = null
      try {
        $.ui.status(undefined)
      } catch {
        // The session is going away; nothing depends on the line.
      }
    }

    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    try {
      // A survey already owns the band; a quiet orbit owns nothing.
      if (e.props.hasSurvey) return next(e)
      const current = (await readState($, view)) ?? EMPTY_VIEW
      const rows = liveRows(current)
      if (rows.length === 0) return next(e)

      ensureTimer($, options)
      const now = await $.clock.now()
      const { Box, Text } = $.ui.resolve(e)
      const width = Math.max(20, e.props.bodyColumns)
      const room = Math.max(1, e.props.maxRows)

      return (
        <Box flexDirection="column">
          {rows.slice(0, room).map(row => {
            const meta = rowMeta(row, now)
            const title = clip(
              row.title,
              Math.max(6, width - meta.length - (row.kind === 'data_job' ? 9 : 5)),
            )
            return (
              <Box key={row.id} flexDirection="row">
                <Text bold color={phaseColor(row.phase)}>
                  {phaseGlyph(row.phase)}
                </Text>
                {row.kind === 'data_job' && (
                  <Text bold backgroundColor={C.job} color={C.jobFg}>
                    {' job '}
                  </Text>
                )}
                <Text bold>{` ${title} `}</Text>
                <Text dimColor wrap="truncate-end">
                  {meta}
                </Text>
              </Box>
            )
          })}
        </Box>
      )
    } catch (error) {
      log($, `AbovePrompt render failed: ${describe(error)}`)
      return next(e)
    }
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e, next) => {
    try {
      ensureTimer($, options)
      const current = (await readState($, view)) ?? EMPTY_VIEW
      const openId = (await readState($, expandedId)) ?? null
      const openFinished = (await readState($, finishedOpen)) ?? false
      const now = await $.clock.now()
      const width = Math.max(24, e.props.bodyColumns)
      const toggleRow = (id: string): Promise<void> =>
        updateState($, expandedId, previous =>
          previous === id ? null : id,
        ).then(() => refresh($, options))
      const toggleFinished = (): Promise<void> =>
        updateState($, finishedOpen, previous => !previous).then(() =>
          refresh($, options),
        )

      if (e.surface === 'terminal') {
        const { Box, Text, Button } = $.ui.resolve(e)
        return (
          <PaneTree
            kit={{ Box, Text, Button, Svg: null }}
            view={current}
            expandedId={openId}
            finishedOpen={openFinished}
            now={now}
            width={width}
            onToggleRow={toggleRow}
            onToggleFinished={toggleFinished}
          />
        )
      }

      const { Box, Text, Button, Svg } = $.ui.resolve(e)
      return (
        <PaneTree
          kit={{ Box, Text, Button, Svg }}
          view={current}
          expandedId={openId}
          finishedOpen={openFinished}
          now={now}
          width={width}
          onToggleRow={toggleRow}
          onToggleFinished={toggleFinished}
        />
      )
    } catch (error) {
      log($, `Pane render failed: ${describe(error)}`)
      return next(e)
    }
  })
}
