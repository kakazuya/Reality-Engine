// Fixture records in the shapes dsh-worker writes: status.json, job.json and
// heartbeat.json. Tests serve these through a mocked $.fs; nothing here reads
// the live runtime folder.

export const NOW = Date.UTC(2026, 9, 24, 12, 0, 0)
export const FIXTURE_ROOT = 'C:/dsh-fixtures/jobs'

const at = (minutesFromNow: number): string =>
  new Date(NOW + minutesFromNow * 60_000).toISOString()

export const RUNNING_ID = '20261024T114000Z-aaaaaaaa'
export const STALLED_ID = '20261024T111000Z-bbbbbbbb'
export const FINISHED_ID = '20261023T100000Z-cccccccc'
export const FAILED_ID = '20261022T100000Z-dddddddd'
export const UNREADABLE_ID = '20261024T115000Z-eeeeeeee'

export const FIXTURE_IDS = [
  RUNNING_ID,
  STALLED_ID,
  FINISHED_ID,
  FAILED_ID,
  UNREADABLE_ID,
] as const

export const FIXTURE_ENTRIES = FIXTURE_IDS.map(name => ({
  name,
  kind: 'dir' as const,
  size: 0,
  mtimeMs: 0,
  isLink: false,
}))

function status(record: Record<string, unknown>): string {
  return JSON.stringify({ schema: 1, ...record }, null, 2)
}

function job(record: Record<string, unknown>): string {
  return JSON.stringify({ schema: 1, ...record }, null, 2)
}

function heartbeat(record: Record<string, unknown>): string {
  return JSON.stringify(
    { schema: 'dsh-heartbeat-status/1', ...record },
    null,
    2,
  )
}

const RUNNING_STATUS = status({
  job_id: RUNNING_ID,
  kind: 'worker',
  phase: 'running',
  started_at: at(-20),
  updated_at: at(-1),
  finished_at: null,
  worker_activity_at: at(-5),
  worker_pid: 1001,
  controller_lease: {
    deadline: at(50),
    lease_seconds: 7200,
    remaining_seconds: 3000,
  },
})

const RUNNING_JOB = job({
  job_id: RUNNING_ID,
  kind: 'worker',
  created_at: at(-20),
  brief_first_line: '# Task: Fix the resource watchdog',
  task_file: 'tasks\\dsh_tasks\\WATCHDOG_LAPTOP_2026-10-24.md',
  workspace: 'C:\\IDM-worktrees\\aaaa',
  worktree: {
    enabled: true,
    branch: `dsh/${RUNNING_ID}`,
    path: 'C:\\IDM-worktrees\\aaaa',
  },
})

const RUNNING_HEARTBEAT = heartbeat({
  state: 'running',
  started_at: at(-20),
  updated_at: at(-5),
  heartbeat: {
    activity_count: 40,
    awaiting_input: false,
    last_activity_at: at(-5),
    last_activity_kind: 'step_output',
    events: [
      { at: at(-6), kind: 'tool_call', detail: { tool: 'read' } },
      { at: at(-6), kind: 'tool_result', detail: { tool: 'unknown' } },
      { at: at(-5.5), kind: 'tool_call', detail: { tool: 'grep' } },
      { at: at(-5.5), kind: 'tool_result', detail: { tool: 'unknown' } },
      { at: at(-5), kind: 'tool_call', detail: { tool: 'pwsh' } },
      { at: at(-5), kind: 'step_output', detail: { phase: 'step_end' } },
    ],
  },
})

const STALLED_STATUS = status({
  job_id: STALLED_ID,
  kind: 'worker',
  phase: 'running',
  started_at: at(-50),
  updated_at: at(-35),
  worker_activity_at: at(-35),
  controller_lease: { deadline: at(10), lease_seconds: 7200 },
})

const STALLED_JOB = job({
  job_id: STALLED_ID,
  kind: 'worker',
  created_at: at(-50),
  brief_first_line: '# Task: Chunk every FY26 annual report',
  task_file: 'tasks\\dsh_tasks\\FY26_AR_CHUNKING_2026-10-24.md',
  worktree: null,
})

const STALLED_HEARTBEAT = heartbeat({
  state: 'running',
  heartbeat: {
    activity_count: 12,
    awaiting_input: false,
    last_activity_at: at(-35),
    last_activity_kind: 'tool_call',
    events: [
      { at: at(-36), kind: 'tool_call', detail: { tool: 'read' } },
      { at: at(-35), kind: 'tool_call', detail: { tool: 'write' } },
    ],
  },
})

const FINISHED_STATUS = status({
  job_id: FINISHED_ID,
  kind: 'worker',
  phase: 'finished',
  started_at: at(-120),
  updated_at: at(-60),
  finished_at: at(-60),
  outcome: 'ok',
})

const FINISHED_JOB = job({
  job_id: FINISHED_ID,
  kind: 'worker',
  created_at: at(-120),
  brief_first_line: '# Task: Rebuild search index',
  worktree: { enabled: true, branch: 'dsh/rebuild-search' },
})

const FAILED_STATUS = status({
  job_id: FAILED_ID,
  kind: 'worker',
  phase: 'failed',
  started_at: at(-1590),
  updated_at: at(-1530),
  finished_at: at(-1530),
  error: 'exit 2',
})

const FAILED_JOB = job({
  job_id: FAILED_ID,
  kind: 'worker',
  created_at: at(-1590),
  brief_first_line: '# Task: Backfill price history',
})

const UNREADABLE_JOB = job({
  job_id: UNREADABLE_ID,
  kind: 'worker',
  created_at: at(-10),
  brief_first_line: '# Task: Mid-write job',
})

export const FIXTURE_FILES: Record<string, string> = {
  [`${FIXTURE_ROOT}/${RUNNING_ID}/status.json`]: RUNNING_STATUS,
  [`${FIXTURE_ROOT}/${RUNNING_ID}/job.json`]: RUNNING_JOB,
  [`${FIXTURE_ROOT}/${RUNNING_ID}/heartbeat.json`]: RUNNING_HEARTBEAT,
  [`${FIXTURE_ROOT}/${RUNNING_ID}/brief.md`]:
    '# Task: Fix the resource watchdog\n\nDetails.',

  [`${FIXTURE_ROOT}/${STALLED_ID}/status.json`]: STALLED_STATUS,
  [`${FIXTURE_ROOT}/${STALLED_ID}/job.json`]: STALLED_JOB,
  [`${FIXTURE_ROOT}/${STALLED_ID}/heartbeat.json`]: STALLED_HEARTBEAT,
  [`${FIXTURE_ROOT}/${STALLED_ID}/brief.md`]:
    '# Task: Chunk every FY26 annual report\n',

  [`${FIXTURE_ROOT}/${FINISHED_ID}/status.json`]: FINISHED_STATUS,
  [`${FIXTURE_ROOT}/${FINISHED_ID}/job.json`]: FINISHED_JOB,
  [`${FIXTURE_ROOT}/${FINISHED_ID}/heartbeat.json`]: heartbeat({
    state: 'finished',
    heartbeat: {
      activity_count: 9,
      last_activity_at: at(-61),
      events: [{ at: at(-61), kind: 'tool_call' }],
    },
  }),

  [`${FIXTURE_ROOT}/${FAILED_ID}/status.json`]: FAILED_STATUS,
  [`${FIXTURE_ROOT}/${FAILED_ID}/job.json`]: FAILED_JOB,

  // A status record caught mid-write: a truncated JSON body.
  [`${FIXTURE_ROOT}/${UNREADABLE_ID}/status.json`]: '{"phase": "runn',
  [`${FIXTURE_ROOT}/${UNREADABLE_ID}/job.json`]: UNREADABLE_JOB,
}
