// Fixture records in the shapes dsh-worker writes: status.json, job.json,
// heartbeat.json, result.md.events.jsonl and result.md. Tests serve these
// through a mocked $.fs; nothing here reads the live runtime folder.

export const NOW = Date.UTC(2026, 9, 24, 12, 0, 0)
export const FIXTURE_ROOT = 'C:/dsh-fixtures/jobs'

const at = (minutesFromNow: number): string =>
  new Date(NOW + minutesFromNow * 60_000).toISOString()

export const RUNNING_ID = '20261024T114000Z-aaaaaaaa'
export const STALLED_ID = '20261024T111000Z-bbbbbbbb'
export const UNREADABLE_ID = '20261024T115000Z-eeeeeeee'
export const FINISHED_ID = '20261024T100000Z-cccccccc'
export const FAILED_TODAY_ID = '20261024T110000Z-ffffffff'
export const CANCELLED_ID = '20261024T113000Z-99999999'
export const FAILED_OLD_ID = '20261023T090000Z-dddddddd'
export const DATA_RUNNING_ID = '20261024T115500Z-da7a0001'
export const DATA_FINISHED_ID = '20261024T112000Z-da7a0002'
export const DATA_FAILED_ID = '20261024T111500Z-da7a0003'
export const DATA_OLD_ID = '20261023T230000Z-da7a0004'
/** Started after `APP_START`, so the idle rule has something to show. It is
 * not in `FIXTURE_ENTRIES`: tests that want the app already busy add it. */
export const RECENT_ID = '20261024T115900Z-1a2b3c4d'
export const RECENT_ENTRY = {
  name: RECENT_ID,
  kind: 'dir' as const,
  size: 0,
  mtimeMs: 0,
  isLink: false,
}

/** A session start six minutes before `NOW`: recent enough that the jobs
 * starting at -5m and -1m are fresh, late enough that the old ones are not. */
export const APP_START = NOW - 6 * 60_000

export const FIXTURE_IDS = [
  RUNNING_ID,
  STALLED_ID,
  UNREADABLE_ID,
  FINISHED_ID,
  FAILED_TODAY_ID,
  CANCELLED_ID,
  FAILED_OLD_ID,
  DATA_RUNNING_ID,
  DATA_FINISHED_ID,
  DATA_FAILED_ID,
  DATA_OLD_ID,
] as const

export const SESSION_A = 'alpha-1001-20261024T070352Z'
export const SESSION_B = 'beta-1002-20261023T221500Z'

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
  owner_session: SESSION_A,
  controller_lease: {
    deadline: at(100),
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
  owner_session: SESSION_A,
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
      { at: at(-5.5), kind: 'tool_call', detail: { tool: 'grep' } },
      { at: at(-5), kind: 'tool_call', detail: { tool: 'pwsh' } },
      { at: at(-5), kind: 'step_output', detail: { phase: 'step_end' } },
    ],
  },
})

const RUNNING_EVENTS = [
  '{"type":"session","sessionId":"session-run"}',
  '{"type":"status","phase":"turn_start"}',
  '{"type":"tool_call","tool":"read","input":{"file_path":"a.md"}}',
  '{"type":"tool_result","status":"completed"}',
  '{"type":"status","phase":"step_end","usage":{"outputTokens":1000}}',
  '{"type":"tool_call","tool":"grep","input":{"pattern":"lease"}}',
  '{"type":"status","phase":"step_end","usage":{"output_tokens":2600}}',
  '{"type":"tool_call","tool":"write","input":{"file_path":"C:\\\\ws\\\\a.ts"}}',
  '{"type":"tool_call","tool":"pwsh","input":{"description":"npm test"}}',
  '',
].join('\n')

const STALLED_STATUS = status({
  job_id: STALLED_ID,
  kind: 'worker',
  phase: 'running',
  started_at: at(-50),
  updated_at: at(-35),
  worker_activity_at: at(-35),
  owner_session: SESSION_A,
  controller_lease: { deadline: at(10), lease_seconds: 7200 },
})

const STALLED_JOB = job({
  job_id: STALLED_ID,
  kind: 'worker',
  created_at: at(-50),
  brief_first_line: '# Task: Chunk every FY26 annual report',
  task_file: 'tasks\\dsh_tasks\\FY26_AR_CHUNKING_2026-10-24.md',
  workspace: 'C:\\IDM-worktrees\\bbbb',
  owner_session: SESSION_A,
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

const STALLED_EVENTS = [
  '{"type":"tool_call","tool":"read","input":{"file_path":"b.md"}}',
  '{"type":"tool_call","tool":"write","input":{"file_path":"C:\\\\ws\\\\b.ts"}}',
  '',
].join('\n')

const FINISHED_STATUS = status({
  job_id: FINISHED_ID,
  kind: 'worker',
  phase: 'finished',
  started_at: at(-120),
  updated_at: at(-60),
  finished_at: at(-60),
  outcome: 'ok',
  exit_code: 0,
  owner_session: SESSION_A,
})

const FINISHED_JOB = job({
  job_id: FINISHED_ID,
  kind: 'worker',
  created_at: at(-120),
  brief_first_line: '# Task: Rebuild search index',
  workspace: 'C:\\IDM-worktrees\\cccc',
  owner_session: SESSION_A,
  worktree: { enabled: true, branch: 'dsh/rebuild-search' },
})

const FINISHED_EVENTS = [
  '{"type":"tool_call","tool":"read","input":{"file_path":"index.py"}}',
  '{"type":"status","phase":"step_end","usage":{"outputTokens":800}}',
  '',
].join('\n')

const FAILED_TODAY_STATUS = status({
  job_id: FAILED_TODAY_ID,
  kind: 'worker',
  phase: 'failed',
  started_at: at(-75),
  updated_at: at(-45),
  finished_at: at(-45),
  exit_code: 2,
  owner_session: SESSION_B,
})

const FAILED_TODAY_JOB = job({
  job_id: FAILED_TODAY_ID,
  kind: 'worker',
  created_at: at(-75),
  brief_first_line: '# Task: Backfill price history',
  owner_session: SESSION_B,
})

const CANCELLED_STATUS = status({
  job_id: CANCELLED_ID,
  kind: 'worker',
  phase: 'cancelled',
  started_at: at(-40),
  updated_at: at(-20),
  finished_at: at(-20),
  exit_code: 1,
  owner_session: SESSION_B,
})

const CANCELLED_JOB = job({
  job_id: CANCELLED_ID,
  kind: 'worker',
  created_at: at(-40),
  brief_first_line: '# Task: Cancelled experiment',
  owner_session: SESSION_B,
})

const FAILED_OLD_STATUS = status({
  job_id: FAILED_OLD_ID,
  kind: 'worker',
  phase: 'failed',
  started_at: at(-1590),
  updated_at: at(-1530),
  finished_at: at(-1530),
  error: 'exit 2',
  owner_session: SESSION_B,
})

const FAILED_OLD_JOB = job({
  job_id: FAILED_OLD_ID,
  kind: 'worker',
  created_at: at(-1590),
  brief_first_line: '# Task: Old failed job',
  owner_session: SESSION_B,
})

const UNREADABLE_JOB = job({
  job_id: UNREADABLE_ID,
  kind: 'worker',
  created_at: at(-10),
  brief_first_line: '# Task: Mid-write job',
  owner_session: SESSION_A,
})

const RECENT_STATUS = status({
  job_id: RECENT_ID,
  kind: 'worker',
  phase: 'running',
  started_at: at(-1),
  updated_at: at(-1),
  worker_activity_at: at(-1),
  owner_session: SESSION_B,
  controller_lease: { deadline: at(60), lease_seconds: 7200 },
})

const RECENT_JOB = job({
  job_id: RECENT_ID,
  kind: 'worker',
  created_at: at(-1),
  brief_first_line: '# Task: Smoke the reconcile pass',
  workspace: 'C:\\IDM-worktrees\\recent',
  owner_session: SESSION_B,
  worktree: { enabled: true, branch: 'dsh/smoke-reconcile' },
})

const RECENT_HEARTBEAT = heartbeat({
  state: 'running',
  heartbeat: {
    activity_count: 3,
    awaiting_input: false,
    last_activity_at: at(-1),
    last_activity_kind: 'tool_call',
    events: [
      { at: at(-1), kind: 'tool_call', detail: { tool: 'pwsh' } },
    ],
  },
})

const RECENT_EVENTS = [
  '{"type":"tool_call","tool":"pwsh","input":{"description":"pytest"}}',
  '',
].join('\n')

function dataStatus(
  id: string,
  phase: string,
  startedAt: string,
  finishedAt: string | null,
  exitCode: number | null,
  owner: string,
): string {
  return status({
    job_id: id,
    kind: 'data_job',
    phase,
    started_at: startedAt,
    updated_at: finishedAt ?? startedAt,
    finished_at: finishedAt,
    exit_code: exitCode,
    owner_session: owner,
    controller_lease: { deadline: at(90), lease_seconds: 7200 },
  })
}

function dataJob(id: string, name: string, owner: string): string {
  return job({
    job_id: id,
    kind: 'data_job',
    created_at: at(-30),
    owner_session: owner,
    data_job: {
      name,
      description: `${name} data run`,
      cadence: 'daily',
      enabled: false,
    },
  })
}

export const FIXTURE_FILES: Record<string, string> = {
  [`${FIXTURE_ROOT}/${RUNNING_ID}/status.json`]: RUNNING_STATUS,
  [`${FIXTURE_ROOT}/${RUNNING_ID}/job.json`]: RUNNING_JOB,
  [`${FIXTURE_ROOT}/${RUNNING_ID}/heartbeat.json`]: RUNNING_HEARTBEAT,
  [`${FIXTURE_ROOT}/${RUNNING_ID}/brief.md`]:
    '# Task: Fix the resource watchdog\n\nDetails.',
  [`${FIXTURE_ROOT}/${RUNNING_ID}/result.md`]:
    'Streaming line one\nStreaming line two',
  [`${FIXTURE_ROOT}/${RUNNING_ID}/result.md.events.jsonl`]: RUNNING_EVENTS,

  [`${FIXTURE_ROOT}/${STALLED_ID}/status.json`]: STALLED_STATUS,
  [`${FIXTURE_ROOT}/${STALLED_ID}/job.json`]: STALLED_JOB,
  [`${FIXTURE_ROOT}/${STALLED_ID}/heartbeat.json`]: STALLED_HEARTBEAT,
  [`${FIXTURE_ROOT}/${STALLED_ID}/brief.md`]:
    '# Task: Chunk every FY26 annual report\n',
  [`${FIXTURE_ROOT}/${STALLED_ID}/result.md.events.jsonl`]: STALLED_EVENTS,

  [`${FIXTURE_ROOT}/${UNREADABLE_ID}/status.json`]: '{"phase": "runn',
  [`${FIXTURE_ROOT}/${UNREADABLE_ID}/job.json`]: UNREADABLE_JOB,

  [`${FIXTURE_ROOT}/${RECENT_ID}/status.json`]: RECENT_STATUS,
  [`${FIXTURE_ROOT}/${RECENT_ID}/job.json`]: RECENT_JOB,
  [`${FIXTURE_ROOT}/${RECENT_ID}/heartbeat.json`]: RECENT_HEARTBEAT,
  [`${FIXTURE_ROOT}/${RECENT_ID}/brief.md`]: '# Task: Smoke the reconcile pass\n',
  [`${FIXTURE_ROOT}/${RECENT_ID}/result.md.events.jsonl`]: RECENT_EVENTS,

  [`${FIXTURE_ROOT}/${FINISHED_ID}/status.json`]: FINISHED_STATUS,
  [`${FIXTURE_ROOT}/${FINISHED_ID}/job.json`]: FINISHED_JOB,
  [`${FIXTURE_ROOT}/${FINISHED_ID}/heartbeat.json`]: heartbeat({
    state: 'finished',
    heartbeat: {
      activity_count: 9,
      last_activity_at: at(-61),
      events: [{ at: at(-61), kind: 'tool_call', detail: { tool: 'read' } }],
    },
  }),
  [`${FIXTURE_ROOT}/${FINISHED_ID}/brief.md`]:
    '# Task: Rebuild search index\n',
  [`${FIXTURE_ROOT}/${FINISHED_ID}/result.md`]:
    '# Search index rebuilt\n\n1,204 chunks indexed\n',
  [`${FIXTURE_ROOT}/${FINISHED_ID}/result.md.events.jsonl`]:
    FINISHED_EVENTS,

  [`${FIXTURE_ROOT}/${FAILED_TODAY_ID}/status.json`]: FAILED_TODAY_STATUS,
  [`${FIXTURE_ROOT}/${FAILED_TODAY_ID}/job.json`]: FAILED_TODAY_JOB,

  [`${FIXTURE_ROOT}/${CANCELLED_ID}/status.json`]: CANCELLED_STATUS,
  [`${FIXTURE_ROOT}/${CANCELLED_ID}/job.json`]: CANCELLED_JOB,

  [`${FIXTURE_ROOT}/${FAILED_OLD_ID}/status.json`]: FAILED_OLD_STATUS,
  [`${FIXTURE_ROOT}/${FAILED_OLD_ID}/job.json`]: FAILED_OLD_JOB,

  [`${FIXTURE_ROOT}/${DATA_RUNNING_ID}/status.json`]: dataStatus(
    DATA_RUNNING_ID,
    'running',
    at(-5),
    null,
    null,
    SESSION_B,
  ),
  [`${FIXTURE_ROOT}/${DATA_RUNNING_ID}/job.json`]: dataJob(
    DATA_RUNNING_ID,
    'insider_trades',
    SESSION_B,
  ),
  [`${FIXTURE_ROOT}/${DATA_RUNNING_ID}/stdout.log`]: '',

  [`${FIXTURE_ROOT}/${DATA_FINISHED_ID}/status.json`]: dataStatus(
    DATA_FINISHED_ID,
    'finished',
    at(-90),
    at(-40),
    0,
    SESSION_A,
  ),
  [`${FIXTURE_ROOT}/${DATA_FINISHED_ID}/job.json`]: dataJob(
    DATA_FINISHED_ID,
    'market_raw_exchange',
    SESSION_A,
  ),

  [`${FIXTURE_ROOT}/${DATA_FAILED_ID}/status.json`]: dataStatus(
    DATA_FAILED_ID,
    'failed',
    at(-70),
    at(-50),
    2,
    SESSION_B,
  ),
  [`${FIXTURE_ROOT}/${DATA_FAILED_ID}/job.json`]: dataJob(
    DATA_FAILED_ID,
    'bse_announcements',
    SESSION_B,
  ),

  [`${FIXTURE_ROOT}/${DATA_OLD_ID}/status.json`]: dataStatus(
    DATA_OLD_ID,
    'finished',
    at(-1560),
    at(-1500),
    0,
    SESSION_A,
  ),
  [`${FIXTURE_ROOT}/${DATA_OLD_ID}/job.json`]: dataJob(
    DATA_OLD_ID,
    'nifty_index',
    SESSION_A,
  ),
}

const BASE64 =
  'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

/** UTF-8 -> padded base64, for the `fs.read { as: "bytes" }` mock. */
export function encodeBase64(text: string): string {
  const bytes = new TextEncoder().encode(text)
  let output = ''
  for (let index = 0; index < bytes.length; index += 3) {
    const a = bytes[index] ?? 0
    const b = bytes[index + 1] ?? 0
    const c = bytes[index + 2] ?? 0
    const chunk = (a << 16) | (b << 8) | c
    output += BASE64[(chunk >> 18) & 63] ?? '='
    output += BASE64[(chunk >> 12) & 63] ?? '='
    output += index + 1 < bytes.length ? (BASE64[(chunk >> 6) & 63] ?? '=') : '='
    output += index + 2 < bytes.length ? (BASE64[chunk & 63] ?? '=') : '='
  }
  return output
}

export function byteLength(text: string): number {
  return new TextEncoder().encode(text).length
}
