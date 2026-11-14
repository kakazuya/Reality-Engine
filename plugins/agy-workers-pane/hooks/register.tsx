import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { AgyRow } from '../types'

// Live agy jobs, read from the agy-worker runtime (job.json, brief.md, events.jsonl).
const ROOT = 'C:/Users/warri/Downloads/Info_Diffusion_Model/plugins/agy-worker/runtime/jobs'
const REFRESH_MS = 15_000
const SCAN_LIMIT = 30

const rows = atom({ plugin: 'agy-workers', key: 'rows' } as const, [] as AgyRow[])
let timer: { cancel: () => void } | null = null
const sizes = new Map<string, { size: number; row: AgyRow }>()

async function text($: EngineInterface, path: string): Promise<string | null> {
  try {
    return await $.fs.read(path)
  } catch {
    return null
  }
}

function titleOf(brief: string | null, id: string): string {
  const first = (brief ?? '').split(/\r?\n/).find(l => l.trim() !== '') ?? id
  return first.replace(/^#+\s*/, '').trim() || id
}

function countEvents(body: string, base: AgyRow): AgyRow {
  let tools = 0, steps = 0, output = 0, cached = 0, input = 0
  for (const line of body.split('\n')) {
    if (!line.includes('step_update')) continue
    let e: any
    try {
      e = JSON.parse(line)
    } catch {
      continue
    }
    const su = e?.step_update
    if (!su || su.state !== 'DONE') continue
    steps += 1
    if (su.step_type === 'tool') tools += 1
    const u = su.usage ?? {}
    output += typeof u.output_tokens === 'number' ? u.output_tokens : 0
    cached += typeof u.cache_read_tokens === 'number' ? u.cache_read_tokens : 0
    input += typeof u.input_tokens === 'number' ? u.input_tokens : 0
  }
  return { ...base, tools, steps, output, cached, input }
}

async function refresh($: EngineInterface): Promise<void> {
  let ids: string[] = []
  try {
    ids = (await $.fs.list(ROOT))
      .filter(x => x.kind === 'dir')
      .map(x => x.name)
      .sort()
      .reverse()
      .slice(0, SCAN_LIMIT)
  } catch {
    await update($, rows, () => [])
    return
  }
  const live: AgyRow[] = []
  for (const id of ids) {
    const dir = `${ROOT}/${id}`
    const jobText = await text($, `${dir}/job.json`)
    if (jobText === null) continue
    let job: any
    try {
      job = JSON.parse(jobText)
    } catch {
      continue
    }
    if (job?.phase !== 'running') continue
    try {
      await $.fs.stat(`${dir}/exit.json`)
      continue // finished
    } catch {
      // no exit.json: still running
    }
    let size = 0, mtime: number | null = null
    try {
      const st = await $.fs.stat(`${dir}/events.jsonl`)
      size = st.size
      mtime = st.mtimeMs
    } catch {
      // no events yet
    }
    const cachedRow = sizes.get(id)
    let row: AgyRow
    if (cachedRow && cachedRow.size === size) {
      row = { ...cachedRow.row, lastEventAt: mtime }
    } else {
      const base: AgyRow = {
        id,
        title: cachedRow?.row.title ?? titleOf(await text($, `${dir}/brief.md`), id),
        model: String(job.model ?? '?'),
        startedAt: Date.parse(job.created_at ?? '') || 0,
        lastEventAt: mtime,
        tools: 0, steps: 0, output: 0, cached: 0, input: 0,
      }
      const body = size > 0 ? await text($, `${dir}/events.jsonl`) : null
      row = body === null ? base : countEvents(body, base)
      sizes.set(id, { size, row })
    }
    live.push(row)
  }
  await update($, rows, () => live)
}

function ensureTimer($: EngineInterface): void {
  if (timer !== null) return
  timer = $.clock.every(REFRESH_MS, () => {
    void refresh($).catch(() => undefined)
  })
}

function k(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

function dur(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000))
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m ${r}s`
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    ensureTimer($)
    void refresh($).catch(() => undefined)
    return next(e)
  })

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    try {
      if (e.props.hasSurvey) return next(e)
      ensureTimer($)
      const list = (await read($, rows)) ?? []
      if (list.length === 0) {
        void refresh($).catch(() => undefined)
        return next(e)
      }
      const now = await $.clock.now()
      const { Box, Text } = $.ui.resolve(e)
      const width = Math.max(20, e.props.bodyColumns)
      const mine = (
        <Box flexDirection="column">
          {list.slice(0, Math.max(1, e.props.maxRows)).map(r => {
            const idle = r.lastEventAt === null ? 0 : Math.floor((now - r.lastEventAt) / 60000)
            const meta = `${r.tools} tools · ${r.steps} steps · ${k(r.output)} out · ${k(r.cached)} cached · idle ${idle}m · ${dur(now - r.startedAt)}`
            const room = Math.max(6, width - meta.length - 10)
            const title = r.title.length > room ? `${r.title.slice(0, room - 1)}…` : r.title
            return (
              <Box key={r.id} flexDirection="row">
                <Text bold color="magenta">{'◆'}</Text>
                <Text bold>{` agy ${title} `}</Text>
                <Text dimColor wrap="truncate-end">{meta}</Text>
              </Box>
            )
          })}
        </Box>
      )
      return mine
    } catch {
      return next(e)
    }
  })
}
