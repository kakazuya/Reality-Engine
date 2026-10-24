import assert from 'node:assert/strict'

import {
  FAILED_ID,
  FINISHED_ID,
  FIXTURE_FILES,
  FIXTURE_ROOT,
  NOW,
  RUNNING_ID,
  STALLED_ID,
  UNREADABLE_ID,
} from '../plugins/dsh-workers-pane/hooks/fixtures.ts'
import {
  LEASE_WARN_MS,
  failedStartMeta,
  leaseColor,
  pickRows,
  rowOf,
  statusMeta,
  viewOf,
} from '../plugins/dsh-workers-pane/hooks/rows.ts'

const fixture = path => JSON.parse(FIXTURE_FILES[path])
const statusOf = id => fixture(`${FIXTURE_ROOT}/${id}/status.json`)

const running = rowOf(
  RUNNING_ID,
  statusOf(RUNNING_ID),
  fixture(`${FIXTURE_ROOT}/${RUNNING_ID}/job.json`),
  fixture(`${FIXTURE_ROOT}/${RUNNING_ID}/heartbeat.json`),
  null,
  NOW,
)
assert.equal(running.phase, 'running')
assert.equal(running.title, 'Fix the resource watchdog')
assert.equal(running.toolCalls, 3)
assert.equal(running.idleMs, 5 * 60_000)
assert.equal(running.elapsedMs, 20 * 60_000)
assert.equal(running.leaseMs, 50 * 60_000)
assert.equal(running.branch, `dsh/${RUNNING_ID}`)

const stalled = rowOf(STALLED_ID, statusOf(STALLED_ID), null, null, null, NOW)
assert.equal(stalled.phase, 'stalled')
assert.equal(leaseColor(stalled.leaseMs), 'error')
assert.equal(leaseColor(LEASE_WARN_MS), undefined)
assert.equal(statusMeta('x', {
  phase: 'running',
  started_at: new Date(NOW - 60 * 60_000).toISOString(),
  worker_activity_at: new Date(NOW - 21 * 60_000).toISOString(),
}, NOW).phase, 'stalled')

const corrupt = rowOf(UNREADABLE_ID, null, null, null, null, NOW)
assert.equal(corrupt.phase, 'unreadable')
assert.equal(corrupt.title, 'eeeeeeee')

const failedStart = failedStartMeta(statusMeta('x', null, NOW), {
  start_failed: true,
  created_at: new Date(NOW - 5 * 60_000).toISOString(),
})
assert.equal(failedStart.phase, 'failed')

const metas = [
  statusMeta(RUNNING_ID, statusOf(RUNNING_ID), NOW),
  statusMeta(STALLED_ID, statusOf(STALLED_ID), NOW),
  statusMeta(FINISHED_ID, statusOf(FINISHED_ID), NOW),
  statusMeta(FAILED_ID, statusOf(FAILED_ID), NOW),
  statusMeta(UNREADABLE_ID, null, NOW),
]
const view = viewOf([], metas, NOW, FIXTURE_ROOT, null)
assert.equal(view.running, 1)
assert.equal(view.stalled, 1)
assert.equal(view.finishedToday, 1)

const picked = pickRows(metas)
assert.deepEqual(picked.map(meta => meta.id), [
  RUNNING_ID,
  STALLED_ID,
  UNREADABLE_ID,
  FINISHED_ID,
  FAILED_ID,
])

console.log('rows self-check passed')
