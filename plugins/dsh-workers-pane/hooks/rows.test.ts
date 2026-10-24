import { expect, test } from 'claude-code/testing'

import {
  FAILED_ID,
  FINISHED_ID,
  FIXTURE_FILES,
  FIXTURE_ROOT,
  NOW,
  RUNNING_ID,
  STALLED_ID,
  UNREADABLE_ID,
} from './fixtures'
import {
  LEASE_WARN_MS,
  failedStartMeta,
  leaseColor,
  pickRows,
  rowOf,
  statusMeta,
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

test('a running row carries its title, tools, idle, elapsed, lease and branch', () => {
  const row = rowOf(
    RUNNING_ID,
    statusOf(RUNNING_ID),
    fixture(`${FIXTURE_ROOT}/${RUNNING_ID}/job.json`),
    fixture(`${FIXTURE_ROOT}/${RUNNING_ID}/heartbeat.json`),
    null,
    NOW,
  )

  expect(row.phase).toBe('running')
  expect(row.shortId).toBe('aaaaaaaa')
  expect(row.title).toBe('Fix the resource watchdog')
  expect(row.toolCalls).toBe(3)
  expect(row.idleMs).toBe(5 * 60_000)
  expect(row.elapsedMs).toBe(20 * 60_000)
  expect(row.leaseMs).toBe(50 * 60_000)
  expect(row.branch).toBe(`dsh/${RUNNING_ID}`)
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

  const row = rowOf(STALLED_ID, statusOf(STALLED_ID), null, null, null, NOW)
  expect(row.phase).toBe('stalled')
  expect(row.idleMs).toBe(35 * 60_000)
})

test('the lease turns red only under 15 minutes', () => {
  expect(leaseColor(LEASE_WARN_MS - 1)).toBe('error')
  expect(leaseColor(LEASE_WARN_MS)).toBeUndefined()
  expect(leaseColor(null)).toBeUndefined()

  const row = rowOf(STALLED_ID, statusOf(STALLED_ID), null, null, null, NOW)
  expect(row.leaseMs).toBe(10 * 60_000)
  expect(leaseColor(row.leaseMs)).toBe('error')
})

test('missing and corrupt records are unreadable, never a throw', () => {
  const row = rowOf(UNREADABLE_ID, null, null, null, null, NOW)
  expect(row.phase).toBe('unreadable')
  expect(row.title).toBe('eeeeeeee')
  expect(row.toolCalls).toBeNull()
  expect(row.elapsedMs).toBeNull()

  const failedStart = failedStartMeta(statusMeta('20261024T115900Z-ffffffff', null, NOW), {
    start_failed: true,
    created_at: iso(NOW - 5 * 60_000),
  })
  expect(failedStart.phase).toBe('failed')
  expect(failedStart.finishedAt).toBe(NOW - 5 * 60_000)
})

test('a data job is titled by its name, with no tool-call count', () => {
  const row = rowOf(
    '20261024T120000Z-data0001',
    { phase: 'finished', started_at: iso(NOW - 60_000), finished_at: iso(NOW) },
    { kind: 'data_job', data_job: { name: 'market_raw_exchange' } },
    null,
    null,
    NOW,
  )

  expect(row.title).toBe('market_raw_exchange')
  expect(row.toolCalls).toBeNull()
  expect(row.phase).toBe('finished')
})

test('a data job reads progress from its log mtime, not a heartbeat', () => {
  const status = {
    kind: 'data_job',
    phase: 'running',
    started_at: iso(NOW - 30 * 60_000),
  }

  const active = statusMeta('data', status, NOW, NOW - 5 * 60_000)
  expect(active.phase).toBe('running')
  expect(active.lastActivityAt).toBe(NOW - 5 * 60_000)

  const quiet = statusMeta('data', status, NOW, NOW - 25 * 60_000)
  expect(quiet.phase).toBe('stalled')
})

test('active rows come first, then the 8 newest finals', () => {
  const running = statusMeta(
    '20261024T120000Z-run00001',
    {
      phase: 'running',
      started_at: iso(NOW - 60_000),
      worker_activity_at: iso(NOW - 60_000),
    },
    NOW,
  )
  const stalled = statusMeta(
    '20261024T115900Z-stop0001',
    {
      phase: 'running',
      started_at: iso(NOW - 2 * 60_000),
      worker_activity_at: iso(NOW - 30 * 60_000),
    },
    NOW,
  )
  const finals = Array.from({ length: 10 }, (_, index) =>
    statusMeta(
      `20261024T${String(11_900 + index).padStart(6, '0')}Z-footer${index}`,
      {
        phase: 'finished',
        started_at: iso(NOW - (120 + index) * 60_000),
        finished_at: iso(NOW - (index + 1) * 60_000),
        updated_at: iso(NOW - (index + 1) * 60_000),
      },
      NOW,
    ),
  )

  const picked = pickRows([...finals, running, stalled], 8)

  expect(picked[0]?.id).toBe(running.id)
  expect(picked[1]?.id).toBe(stalled.id)
  expect(picked.map(meta => meta.id).slice(2)).toEqual(
    finals.slice(0, 8).map(meta => meta.id),
  )
})

test('the header counts the whole scan, not just the shown rows', () => {
  const metas = [
    statusMeta(RUNNING_ID, statusOf(RUNNING_ID), NOW),
    statusMeta(STALLED_ID, statusOf(STALLED_ID), NOW),
    statusMeta(FINISHED_ID, statusOf(FINISHED_ID), NOW),
    statusMeta(FAILED_ID, statusOf(FAILED_ID), NOW),
    statusMeta(UNREADABLE_ID, null, NOW),
  ]

  const view = viewOf([], metas, NOW, FIXTURE_ROOT, null)

  expect(view.running).toBe(1)
  expect(view.stalled).toBe(1)
  // FINISHED_ID finished today; FAILED_ID finished yesterday.
  expect(view.finishedToday).toBe(1)
})
