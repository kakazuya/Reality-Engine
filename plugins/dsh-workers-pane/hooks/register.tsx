import { atom, read as readState, update as updateState } from 'claude-code'
import type { EngineInterface, PluginOptions, Register } from 'claude-code'

import type { WorkerView } from '../types'
import {
  EMPTY_VIEW,
  failedStartMeta,
  formatDuration,
  formatLease,
  isDataJobStatus,
  leaseColor,
  phaseColor,
  phaseGlyph,
  pickRows,
  rowOf,
  statusMeta,
  viewOf,
} from './rows'
import type { StatusMeta, WorkerRow } from './rows'

const PANE = 'dsh-workers'
const COMMAND = 'dsh-workers'
const TITLE = 'DeepSeek workers'
const REFRESH_MS = 15_000
// The runtime folder keeps every job ever run. Only the newest dirs are
// scanned, which is all the pane shows plus the 8 most recent finals.
// ponytail: fixed 60-dir window; make it userConfig if old live jobs matter.
const SCAN_LIMIT = 60
const DEFAULT_ROOT =
  'C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/dsh-worker/runtime/jobs'

const view = atom({ plugin: 'dsh-workers', key: 'view' } as const, EMPTY_VIEW)

let isRefreshing = false
let timer: { cancel: () => void } | null = null

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

function jobPath(root: string, id: string, name: string): string {
  return `${root}/${id}/${name}`
}

type Scanned = {
  id: string
  status: unknown
  meta: StatusMeta
  logMtimeMs: number | null
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

async function readView(
  $: EngineInterface,
  root: string,
  now: number,
): Promise<WorkerView> {
  const entries = await $.fs.list(root)
  const ids = entries
    .filter(entry => entry.kind === 'dir')
    .map(entry => entry.name)
    .sort()
    .reverse()
    .slice(0, SCAN_LIMIT)

  const scanned: Scanned[] = await Promise.all(
    ids.map(async id => {
      const status = await readJson($, jobPath(root, id, 'status.json'))
      return { id, status, meta: statusMeta(id, status, now), logMtimeMs: null }
    }),
  )

  // A failed start has a job.json and no status.json: show it as failed
  // instead of leaving an unreadable row at the top of the pane forever.
  await Promise.all(
    scanned.map(async item => {
      if (item.meta.phase === 'unreadable') {
        item.meta = failedStartMeta(
          item.meta,
          await readJson($, jobPath(root, item.id, 'job.json')),
        )
        return
      }
      if (isDataJobStatus(item.status)) {
        item.logMtimeMs = await readLogMtime($, root, item.id)
        item.meta = statusMeta(item.id, item.status, now, item.logMtimeMs)
      }
    }),
  )

  const metas = scanned.map(item => item.meta)
  const picked = pickRows(metas)
  const byId = new Map(scanned.map(item => [item.id, item]))

  const rows = await Promise.all(
    picked.map(async meta => {
      const [job, heartbeat, brief] = await Promise.all([
        readJson($, jobPath(root, meta.id, 'job.json')),
        readJson($, jobPath(root, meta.id, 'heartbeat.json')),
        readText($, jobPath(root, meta.id, 'brief.md')),
      ])
      return rowOf(
        meta.id,
        byId.get(meta.id)?.status ?? null,
        job,
        heartbeat,
        brief,
        now,
        byId.get(meta.id)?.logMtimeMs ?? null,
      )
    }),
  )

  return viewOf(rows, metas, now, root, null)
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
    const next = await readView($, root, now)
    const stored = await updateState($, view, () => next)
    try {
      $.ui.status(`dsh: ${stored.running} running, ${stored.stalled} stalled`)
    } catch {
      // A status line is a nicety; the pane must still draw without one.
    }
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    await updateState($, view, () => ({
      ...EMPTY_VIEW,
      readAt: now,
      root,
      error: `cannot read ${root}: ${reason}`,
    })).catch(() => undefined)
  } finally {
    isRefreshing = false
  }
}

function activityLine(row: WorkerRow): string {
  const idle =
    row.idleMs === null ? 'last ?' : `last ${formatDuration(row.idleMs)} ago`
  const elapsed =
    row.elapsedMs === null ? '' : ` ${formatDuration(row.elapsedMs)}`
  return `  ${row.phase}${elapsed} · ${idle}`
}

function toolsLine(row: WorkerRow): string {
  return `  tc ${row.toolCalls === null ? '–' : row.toolCalls}`
}

function startTimer($: EngineInterface, options: PluginOptions): void {
  timer?.cancel()
  timer = $.clock.every(REFRESH_MS, () => {
    void refresh($, options)
  })
}

export const register: Register = (on, options) => {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: COMMAND,
      description: 'Show DeepSeek worker jobs in a pane',
    })
    await refresh($, options)
    void $.ui.open({ id: PANE, title: TITLE }).catch(() => undefined)
    startTimer($, options)

    return next(e)
  })

  on('command.run', { command: COMMAND }, async $ => {
    await refresh($, options)
    await $.ui.open({ id: PANE, title: TITLE })
    // A mod hot-loaded into a running session never saw session.start.
    startTimer($, options)

    return { text: `${TITLE} pane opened.` }
  }).catch(async ($, e, next) =>
    next.called
      ? next(e)
      : { text: `${TITLE} pane could not be opened.` },
  )

  on('session.end', async ($, e, next) => {
    timer?.cancel()
    timer = null
    try {
      $.ui.status(undefined)
    } catch {
      // The session is going away; nothing depends on the line.
    }

    return next(e)
  })

  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text } = $.ui.resolve(e)
    const current = (await readState($, view)) ?? EMPTY_VIEW
    const now = await $.clock.now()
    const width = Math.max(24, e.props.bodyColumns)

    return (
      <Box flexDirection="column" width={width}>
        <Text bold wrap="truncate-end">
          {TITLE}
        </Text>
        <Text dimColor wrap="truncate-end">
          {`${current.running} running · ${current.stalled} stalled · ${
            current.finishedToday
          } finished today`}
        </Text>
        {current.error !== null && (
          <Text color="warning" wrap="truncate-end">
            {current.error}
          </Text>
        )}
        {current.rows.length === 0 && current.error === null && (
          <Text dimColor wrap="truncate-end">
            {`No jobs in ${current.root}`}
          </Text>
        )}
        {current.rows.map(row => {
          const color = phaseColor(row.phase)
          const isLeaseShown =
            row.leaseMs !== null &&
            (row.phase === 'running' || row.phase === 'stalled')
          const leaseTint = leaseColor(row.leaseMs)

          return (
            <Box key={row.id} flexDirection="column" marginTop={1}>
              <Text wrap="truncate-end">
                <Text color={color} dimColor={color === undefined}>
                  {phaseGlyph(row.phase)}
                </Text>
                <Text dimColor>{` ${row.shortId} `}</Text>
                {row.title}
              </Text>
              <Text dimColor wrap="truncate-end">
                {activityLine(row)}
              </Text>
              <Text dimColor wrap="truncate-end">
                {toolsLine(row)}
                {isLeaseShown && (
                  <Text
                    color={leaseTint}
                    dimColor={leaseTint === undefined}
                  >{` · lease ${formatLease(row.leaseMs)}`}</Text>
                )}
              </Text>
              {row.branch !== null && (
                <Text dimColor wrap="truncate-end">{`  ⎇ ${row.branch}`}</Text>
              )}
            </Box>
          )
        })}
        <Box marginTop={1}>
          <Text dimColor wrap="truncate-end">
            {`updated ${formatDuration(now - current.readAt)} ago · every 15s`}
          </Text>
        </Box>
      </Box>
    )
  })
}
