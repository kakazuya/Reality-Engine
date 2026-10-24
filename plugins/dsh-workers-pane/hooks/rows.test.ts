import { expect, test } from 'claude-code/testing'

import {
  CANCELLED_ID,
  DATA_FAILED_ID,
  DATA_FINISHED_ID,
  DATA_OLD_ID,
  DATA_RUNNING_ID,
  FAILED_OLD_ID,
  FAILED_TODAY_ID,
  FINISHED_ID,
  FIXTURE_FILES,
  FIXTURE_ROOT,
  NOW,
  RUNNING_ID,
  STALLED_ID,
  UNREADABLE_ID,
} from './fixtures'
import type { WorkerMetrics, WorkerRow } from '../types'
import {
  LEASE_WARN_MS,
  barCells,
  briefLinesOf,
  failedStartMeta,
  formatAgo,
  formatLive,
  formatTokens,
  groupFinished,
  heatRatio,
  idleTone,
  leaseFraction,
  leaseTone,
  resultTailOf,
  rowOf,
  sessionLabel,
  sparkFromEvents,
  statusMeta,
  toolBreakdown,
  viewOf,
} from './rows'

const iso = (ms: number): string => new Date(ms).toISOString()

function fixture(path: string): unknown {
  const text = FIXTURE_FILES[path]
  if (text === undefined) throw new Error(`no fixture at ${path}`)
  return JSON.parse(text) as unknown
}

const statusOf = (id: string): unknown =>
  fixture(`${FIXTURE_ROOT}/${id}/status.json`)

function metricsOfFixture(): WorkerMetrics {
  return {
    toolCalls: 4,
    modelSteps: 2,
    outputTokens: 3600,
    fileWrites: 1,
    lastTool: 'pwsh',
    lastToolTarget: 'npm test',
    byTool: { read: 1, grep: 1, write: 1, pwsh: 1 },
  }
}

function rowFor(id: string, withMetrics = false): WorkerRow {
  return rowOf(
    id,
    id === UNREADABLE_ID ? null : statusOf(id),
    fixture(`${FIXTURE_ROOT}/${id}/job.json`),
    FIXTURE_FILES[`${FIXTURE_ROOT}/${id}/heartbeat.json`] === undefined
      ? null
      : fixture(`${FIXTURE_ROOT}/${id}/heartbeat.json`),
    FIXTURE_FILES[`${FIXTURE_ROOT}/${id}/brief.md`] ?? null,
    NOW,
    null,
    withMetrics ? { metrics: metricsOfFixture() } : {},
  )
}

test('a running row carries its title, live metrics, lease, session and activity', () => {
  const row = rowFor(RUNNING_ID, true)

  expect(row.phase).toBe('running')
  expect(row.kind).toBe('worker')
  expect(row.shortId).toBe('aaaaaaaa')
  expect(row.title).toBe('Fix the resource watchdog')
  expect(row.idleMs).toBe(5 * 60_000)
  expect(row.elapsedMs).toBe(20 * 60_000)
  expect(row.leaseMs).toBe(100 * 60_000)
  expect(row.leaseTotalMs).toBe(2 * 60 * 60_000)
  expect(Math.round((row.leaseMs! / row.leaseTotalMs!) * 1000) / 1000).toBe(
    0.833,
  )
  expect(row.branch).toBe(`dsh/${RUNNING_ID}`)
  expect(row.workspace).toBe('C:\\IDM-worktrees\\aaaa')
  expect(row.ownerSession).toBe('alpha-1001-20261024T070352Z')
  expect(row.metrics?.toolCalls).toBe(4)
  expect(row.briefLines[0]).toBe('Fix the resource watchdog')
  expect(row.briefLines[1]).toBe('Details.')
  expect(row.activity.length).toBe(3)
  expect(row.activity.at(-1)?.text).toContain('pwsh')
  expect(row.activity.at(-1)?.text).toContain('npm test')
})

test('stalled is running with no activity for more than 20 minutes', () => {
  const metaAt = (idleMinutes: number) =>
    statusMeta(
      '20261024T120000Z-stall001',
      {
        phase: 'running',
        started_at: iso(NOW - 60 * 60_000),
        worker_activity_at: iso(NOW - idleMinutes * 60_000),
      },
      NOW,
    )

  expect(metaAt(19).phase).toBe('running')
  expect(metaAt(21).phase).toBe('stalled')

  const row = rowFor(STALLED_ID)
  expect(row.phase).toBe('stalled')
  expect(row.idleMs).toBe(35 * 60_000)
  expect(idleTone(row.idleMs)).toBe('error')
})

test('idle and lease colours follow the 10/20 minute and 15/30 minute rules', () => {
  expect(idleTone(9 * 60_000)).toBeUndefined()
  expect(idleTone(11 * 60_000)).toBe('warning')
  expect(idleTone(21 * 60_000)).toBe('error')

  const total = 2 * 60 * 60_000
  expect(leaseTone(leaseFraction(LEASE_WARN_MS - 1, total), LEASE_WARN_MS - 1)).toBe('error')
  expect(leaseTone(leaseFraction(10 * 60_000, total), 10 * 60_000)).toBe('error')
  expect(leaseTone(leaseFraction(25 * 60_000, total), 25 * 60_000)).toBe('warning')
  expect(leaseTone(leaseFraction(50 * 60_000, total), 50 * 60_000)).toBe('success')
  expect(leaseFraction(30 * 60_000, total)).toBe(0.25)
  expect(leaseFraction(0, total)).toBe(0)
  expect(leaseFraction(-5, total)).toBe(0)
})

test('durations tick in the panel format; tokens use k and M', () => {
  expect(formatLive(16 * 60_000 + 15_000)).toBe('16m 15s')
  expect(formatLive(65 * 60_000)).toBe('1h 05m')
  expect(formatLive(45_000)).toBe('45s')
  expect(formatTokens(999)).toBe('999')
  expect(formatTokens(3_600)).toBe('3.6k')
  expect(formatTokens(12_345)).toBe('12k')
  expect(formatTokens(1_234_567)).toBe('1.2M')
  expect(formatAgo(120 * 60_000)).toBe('2h ago')
})

test('missing and corrupt records are unreadable, never a throw', () => {
  const row = rowOf(UNREADABLE_ID, null, null, null, null, NOW)
  expect(row.phase).toBe('unreadable')
  expect(row.title).toBe('eeeeeeee')
  expect(row.metrics).toBeNull()
  expect(row.elapsedMs).toBeNull()

  const failedStart = failedStartMeta(
    statusMeta('20261024T115900Z-ffffffff', null, NOW),
    {
      start_failed: true,
      created_at: iso(NOW - 5 * 60_000),
    },
  )
  expect(failedStart.phase).toBe('failed')
  expect(failedStart.outcome).toBe('failed')
  expect(failedStart.finishedAt).toBe(NOW - 5 * 60_000)

  // The refresh hands its classified meta back to rowOf; a start failure must
  // not be re-derived as an unreadable row.
  const failedStartRow = rowOf(
    '20261024T115900Z-ffffffff',
    null,
    { start_failed: true, created_at: iso(NOW - 5 * 60_000) },
    null,
    null,
    NOW,
    null,
    { meta: failedStart },
  )
  expect(failedStartRow.phase).toBe('failed')
  expect(failedStartRow.outcome).toBe('failed')
})

test('finished rows show outcome, duration and branch, never last activity', () => {
  const ok = rowFor(FINISHED_ID)
  expect(ok.phase).toBe('finished')
  expect(ok.outcome).toBe('ok')
  expect(ok.elapsedMs).toBe(60 * 60_000)
  expect(ok.branch).toBe('dsh/rebuild-search')
  expect(ok.activity.length).toBe(1)

  const failed = rowFor(FAILED_TODAY_ID)
  expect(failed.phase).toBe('failed')
  expect(failed.outcome).toBe('failed')
  expect(failed.exitCode).toBe(2)

  const cancelled = rowFor(CANCELLED_ID)
  expect(cancelled.phase).toBe('cancelled')
  expect(cancelled.outcome).toBe('cancelled')

  const lost = statusMeta(
    '20261024T110000Z-lost0001',
    { phase: 'lost', started_at: iso(NOW - 60_000), updated_at: iso(NOW) },
    NOW,
  )
  expect(lost.phase).toBe('failed')
})

test('data jobs are titled by name and carry exit code and duration', () => {
  const running = rowFor(DATA_RUNNING_ID)
  expect(running.kind).toBe('data_job')
  expect(running.title).toBe('insider_trades')
  expect(running.phase).toBe('running')
  expect(running.exitCode).toBeNull()

  const finished = rowFor(DATA_FINISHED_ID)
  expect(finished.kind).toBe('data_job')
  expect(finished.title).toBe('market_raw_exchange')
  expect(finished.outcome).toBe('ok')
  expect(finished.exitCode).toBe(0)
  expect(finished.elapsedMs).toBe(50 * 60_000)

  const failed = rowFor(DATA_FAILED_ID)
  expect(failed.outcome).toBe('failed')
  expect(failed.exitCode).toBe(2)
})

test('brief lines and result tail are clipped and skip blank lines', () => {
  expect(
    briefLinesOf('# Task: Fix the resource watchdog\n\nDetails.', null),
  ).toEqual(['Fix the resource watchdog', 'Details.'])
  expect(
    resultTailOf('# Search index rebuilt\n\n1,204 chunks indexed\n', 8),
  ).toEqual(['# Search index rebuilt', '1,204 chunks indexed'])
  expect(resultTailOf(null)).toEqual([])
})

test('sessions get a readable label for the group header', () => {
  expect(sessionLabel('alpha-1001-20261024T070352Z')).toBe(
    'alpha · 24 Oct 07:03Z',
  )
  expect(sessionLabel('beta-1002-20261023T221500Z')).toBe(
    'beta · 23 Oct 22:15Z',
  )
  expect(sessionLabel(null)).toBe('unknown session')
  expect(sessionLabel('solo')).toBe('solo')
})

test('heartbeat timestamps seed the sparkline before the sampler has history', () => {
  const spark = sparkFromEvents(
    [
      { at: iso(NOW - 2 * 60_000) },
      { at: iso(NOW - 60_000) },
      { at: iso(NOW - 60_000) },
      { at: iso(NOW - 45 * 60_000) },
      { at: 'not-a-date' },
    ],
    NOW,
  )
  expect(spark?.[27]).toBe(1)
  expect(spark?.[28]).toBe(2)
  expect(spark?.[29]).toBe(0)
  expect(spark?.[0]).toBe(0)
  expect(sparkFromEvents([], NOW)).toBeNull()
})

test('finished jobs group by owner session, newest group first', () => {
  const rows = [
    rowFor(FINISHED_ID),
    rowFor(DATA_FINISHED_ID),
    rowFor(DATA_OLD_ID),
    rowFor(CANCELLED_ID),
    rowFor(FAILED_TODAY_ID),
    rowFor(DATA_FAILED_ID),
    rowFor(FAILED_OLD_ID),
  ]

  const groups = groupFinished(rows)

  expect(groups.map(group => group.label)).toEqual([
    'beta · 23 Oct 22:15Z',
    'alpha · 24 Oct 07:03Z',
  ])
  expect(groups[0]?.rows.map(row => row.id)).toEqual([
    CANCELLED_ID,
    FAILED_TODAY_ID,
    DATA_FAILED_ID,
    FAILED_OLD_ID,
  ])
  expect(groups[1]?.rows.map(row => row.id)).toEqual([
    DATA_FINISHED_ID,
    FINISHED_ID,
    DATA_OLD_ID,
  ])
  expect(groups[0]?.rows.length).toBe(4)
  expect(groups[1]?.rows.length).toBe(3)
  expect(groups[0]?.spanMs).toBe(1570 * 60_000)
})

test('the view splits running from finished and counts every job kind', () => {
  const rows = [
    rowFor(RUNNING_ID, true),
    rowFor(STALLED_ID),
    rowFor(UNREADABLE_ID),
    rowFor(DATA_RUNNING_ID),
    rowFor(FINISHED_ID),
    rowFor(FAILED_TODAY_ID),
    rowFor(CANCELLED_ID),
    rowFor(DATA_FINISHED_ID),
    rowFor(DATA_FAILED_ID),
    rowFor(DATA_OLD_ID),
    rowFor(FAILED_OLD_ID),
  ]
  const metas = rows.map(row =>
    statusMeta(
      row.id,
      row.id === UNREADABLE_ID ? null : statusOf(row.id),
      NOW,
    ),
  )

  const view = viewOf(rows, metas, NOW, FIXTURE_ROOT, null)

  expect(view.running.map(row => row.id)).toEqual([
    DATA_RUNNING_ID,
    RUNNING_ID,
    STALLED_ID,
    UNREADABLE_ID,
  ])
  expect(view.counts.running).toBe(2)
  expect(view.counts.stalled).toBe(1)
  expect(view.counts.failed).toBe(3)
  expect(view.counts.finished).toBe(3)
  expect(view.finished.length).toBe(7)
  expect(view.finishedGroups.length).toBe(2)
  expect(view.maxima.tools).toBe(20)
})

test('heat ratios clamp and tool bars keep one filled cell', () => {
  expect(heatRatio(null, 10)).toBe(0)
  expect(heatRatio(-1, 10)).toBe(0)
  expect(heatRatio(5, 10)).toBe(0.5)
  expect(heatRatio(50, 10)).toBe(1)
  expect(barCells(0, 10, 5)).toBe('█░░░░')
  expect(barCells(10, 10, 5)).toBe('█████')

  const tools = toolBreakdown(metricsOfFixture())
  expect(tools.map(tool => tool.tool)).toEqual(['grep', 'pwsh', 'read', 'write'])
  expect(tools[0]?.count).toBe(1)
  expect(toolBreakdown(null)).toEqual([])
})
