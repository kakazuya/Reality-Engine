// Per-invocation Cordis control plugin for run_deepseek_harness.py.
//
// dsh-headless is one-shot: its stdin is read once, so appending text to stdin
// is not a live control channel.  This plugin is loaded through a temporary
// --patch overlay and exposes a loopback-only HTTP mailbox.  When the
// supervisor posts a status request, the plugin calls Agent.steer() on the
// same live agent.  steer() is queued for the next model/tool boundary; it
// never aborts a productive reasoning call.
//
// Explicit same-conversation follow-ups (opt-in, bounded):
//   With followupWaitSeconds > 0 this plugin also listens to the supported
//   awaited Agent event `agent/turn-stopping`.  That hook runs when the model
//   owes no response and the turn is about to close.  The listener waits (no
//   model request, no shell sleep) until POST /followup delivers a genuine
//   question.  It then calls Agent.steer(); the agent loop re-reads its inbox
//   and runs one more step in the same turn and conversation.  A follow-up is
//   therefore never sent twice: the endpoint either hands it to the waiter
//   (which steers) or, when no wait is active, steers it itself.  A timeout or
//   shutdown resolves the waiter with no steer, so an ordinary one-shot worker
//   exits naturally.  Status pings keep the old /ping path and are suppressed
//   by the Python supervisor while a deliberate input wait is active.
//
// Security:
//   * bind 127.0.0.1 only, ephemeral port;
//   * the per-run bearer token arrives only through DSH_HEARTBEAT_TOKEN;
//   * the descriptor file contains no token;
//   * requests require the token, run id, POST, and JSON;
//   * browser-origin requests are rejected to reduce local CSRF risk.
//
// Transport acknowledgement is not a model response.  The Python supervisor
// counts only committed dsh events as worker activity.

import { createServer } from 'node:http'
import { timingSafeEqual } from 'node:crypto'
import { renameSync, rmSync, writeFileSync } from 'node:fs'

export const name = 'dsh-heartbeat-control'
export const inject = ['agents']

const MAX_BODY = 64 * 1024
const MAX_FOLLOWUP_CHARS = 4000
const MAX_FOLLOWUP_WAIT_SECONDS = 3600
const HOST = '127.0.0.1'
const PAUSE = new Int32Array(new SharedArrayBuffer(4))

function pause(ms) {
  Atomics.wait(PAUSE, 0, 0, ms)
}

function writeJsonAtomic(file, value) {
  const text = JSON.stringify(value)
  const tmp = `${file}.${process.pid}.tmp`
  writeFileSync(tmp, text, { encoding: 'utf8', mode: 0o600 })
  // Windows can reject renaming over a descriptor the supervisor is reading.
  // Retry briefly, then fall back to a direct small write; readers validate
  // JSON and simply retry on a partial read.
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      renameSync(tmp, file)
      return
    } catch (error) {
      if (!['EPERM', 'EBUSY', 'EACCES'].includes(error?.code)) break
      pause(10 + attempt * 5)
    }
  }
  try {
    for (let attempt = 0; attempt < 8; attempt += 1) {
      try {
        writeFileSync(file, text, { encoding: 'utf8', mode: 0o600 })
        rmSync(tmp, { force: true })
        return
      } catch (error) {
        if (!['EPERM', 'EBUSY', 'EACCES'].includes(error?.code)) break
        pause(10 + attempt * 5)
      }
    }
  } catch {
    // The supervisor will treat an unreadable descriptor as not ready.
  }
}

function tokensEqual(left, right) {
  if (typeof left !== 'string' || typeof right !== 'string') return false
  const a = Buffer.from(left)
  const b = Buffer.from(right)
  return a.length === b.length && timingSafeEqual(a, b)
}

function textOfContent(content) {
  if (!Array.isArray(content)) return ''
  return content
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
}

export function apply(ctx, config) {
  const endpointFile = config?.endpointFile
  if (typeof endpointFile !== 'string' || endpointFile.length === 0) {
    throw new Error('dsh-heartbeat-control: endpointFile is required')
  }
  const followupWaitSeconds = Number(config?.followupWaitSeconds ?? 0)
  if (
    !Number.isFinite(followupWaitSeconds) ||
    followupWaitSeconds < 0 ||
    followupWaitSeconds > MAX_FOLLOWUP_WAIT_SECONDS
  ) {
    throw new Error(
      `dsh-heartbeat-control: followupWaitSeconds must be 0..${MAX_FOLLOWUP_WAIT_SECONDS}`,
    )
  }
  const token = process.env.DSH_HEARTBEAT_TOKEN
  if (typeof token !== 'string' || token.length < 32) {
    throw new Error('dsh-heartbeat-control: DSH_HEARTBEAT_TOKEN is required')
  }
  const runId = process.env.DSH_HEARTBEAT_RUN_ID || null

  let agent = null
  let server = null
  let port = null
  let closed = false
  // One turn-stopping waiter at a time.  A waiter is settled exactly once by a
  // follow-up, a timeout, an abort, agent disposal, or plugin teardown.
  let waiter = null
  let turnStopping = false
  const seenFollowups = new Set()
  const state = {
    schema: 'dsh-heartbeat-control/1',
    state: 'starting',
    host: HOST,
    port: null,
    pid: process.pid,
    run_id: runId,
    session_id: null,
    agent_status: null,
    started_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    closed_at: null,
    last_ping: null,
    pings: 0,
    delivery_errors: 0,
    followup_wait_seconds: followupWaitSeconds,
    awaiting_input: false,
    awaiting_since: null,
    followup_deadline: null,
    followups_delivered: 0,
    last_followup: null,
  }

  const publish = (patch = {}) => {
    Object.assign(state, patch, { updated_at: new Date().toISOString() })
    writeJsonAtomic(endpointFile, state)
  }

  const bind = (candidate) => {
    if (agent !== null || !candidate || typeof candidate.steer !== 'function') return
    // A per-invocation plugin sees one headless run.  Bind the first runtime
    // root; subagents created later are children and must not receive pings.
    let isRoot = false
    try {
      isRoot = ctx.agents.roots().some((root) => root.id === candidate.id)
    } catch {
      isRoot = false
    }
    if (!isRoot) return
    agent = candidate
    publish({ state: 'bound', session_id: candidate.id, agent_status: candidate.status ?? null })
    ctx.logger?.info?.('dsh-heartbeat-control: bound agent %s', candidate.id)
  }

  const settleWaiter = (entry, delivery) => {
    if (!entry || entry.done) return
    entry.done = true
    if (entry.timer !== null) clearTimeout(entry.timer)
    if (entry.signal && entry.onAbort) {
      entry.signal.removeEventListener('abort', entry.onAbort)
    }
    if (waiter === entry) waiter = null
    publish({
      state: 'bound',
      awaiting_input: false,
      awaiting_since: null,
      followup_deadline: null,
    })
    entry.resolve(delivery)
  }

  const waitForFollowup = (signal) => {
    if (followupWaitSeconds <= 0 || agent === null || closed || signal?.aborted) {
      return Promise.resolve(null)
    }
    if (waiter !== null) return Promise.resolve(null)
    return new Promise((resolve) => {
      const now = Date.now()
      const entry = {
        done: false,
        resolve,
        signal,
        timer: null,
        onAbort: null,
        ack: null,
        nack: null,
      }
      entry.onAbort = () => settleWaiter(entry, null)
      signal?.addEventListener('abort', entry.onAbort, { once: true })
      entry.timer = setTimeout(
        () => settleWaiter(entry, null),
        Math.max(1, followupWaitSeconds * 1000),
      )
      waiter = entry
      publish({
        state: 'awaiting-input',
        awaiting_input: true,
        awaiting_since: new Date(now).toISOString(),
        followup_deadline: new Date(now + followupWaitSeconds * 1000).toISOString(),
      })
    })
  }

  const deliverToWaiter = (entry, text, followupId) => {
    // The listener performs the single steer and acknowledges after it
    // succeeds.  The HTTP response therefore means delivered/queued, never a
    // model response.
    const acknowledged = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        entry.ack = null
        entry.nack = null
        reject(new Error('followup-ack-timeout'))
      }, 5000)
      entry.ack = () => {
        clearTimeout(timer)
        resolve()
      }
      entry.nack = (error) => {
        clearTimeout(timer)
        reject(error)
      }
    })
    const delivery = {
      text,
      followup_id: followupId,
      turn: null,
      accept: () => entry.ack?.(),
      reject: (error) => entry.nack?.(error),
    }
    settleWaiter(entry, delivery)
    return acknowledged
  }

  const steer = (text) => {
    if (agent === null) throw new Error('agent-not-bound')
    agent.steer({
      content: [{ type: 'text', text }],
      source: { kind: 'dsh-followup' },
    })
  }

  // Supported awaited hook: it runs when the turn is otherwise about to close.
  // Steering here makes the agent loop re-read its inbox and run one more step
  // in the same turn.  Returning without steering closes the turn normally.
  ctx.on('agent/turn-stopping', async (payload) => {
    if (agent === null || closed || followupWaitSeconds <= 0) return
    if (payload?.agent && payload.agent.id !== agent.id) return
    if (payload?.signal?.aborted) return
    turnStopping = true
    try {
      const delivery = await waitForFollowup(payload?.signal)
      if (!delivery || agent === null || closed) return
      try {
        steer(delivery.text)
        delivery.followup_id = delivery.followup_id || null
        state.followups_delivered += 1
        state.last_followup = {
          at: new Date().toISOString(),
          followup_id: delivery.followup_id,
          chars: delivery.text.length,
          session_id: agent.id,
        }
        publish({
          state: 'bound',
          followups_delivered: state.followups_delivered,
          last_followup: state.last_followup,
        })
        delivery.accept()
      } catch (error) {
        state.delivery_errors += 1
        publish({
          state: 'delivery-error',
          last_ping: { error: String(error?.message ?? error) },
        })
        delivery.reject(error)
      }
    } finally {
      turnStopping = false
    }
  })

  for (const root of ctx.agents.roots()) bind(root)
  ctx.on('agent/created', (payload) => bind(payload?.agent))
  ctx.on('agent/disposed', (payload) => {
    if (agent !== null && payload?.agent?.id === agent.id) {
      if (waiter !== null) settleWaiter(waiter, null)
      agent = null
      publish({ state: 'agent-disposed', agent_status: null })
    }
  })
  ctx.on('agent/status', (payload) => {
    if (agent !== null && payload?.agent?.id === agent.id) {
      // Keep the live value in memory; do not rewrite the descriptor on every
      // status transition (Windows rename-over-open-read is needless churn).
      state.agent_status = payload.status ?? payload.agent.status ?? null
    }
  })

  const reject = (res, status, message) => {
    const body = JSON.stringify({ ok: false, error: message })
    res.writeHead(status, {
      'content-type': 'application/json; charset=utf-8',
      'content-length': Buffer.byteLength(body),
      'cache-control': 'no-store',
    })
    res.end(body)
  }

  const accept = (res, value) => {
    const body = JSON.stringify(value)
    res.writeHead(200, {
      'content-type': 'application/json; charset=utf-8',
      'content-length': Buffer.byteLength(body),
      'cache-control': 'no-store',
    })
    res.end(body)
  }

  const handlePing = (req, res, raw) => {
    if (runId !== null) {
      let body
      try {
        body = JSON.parse(raw)
      } catch {
        reject(res, 400, 'invalid-json')
        return
      }
      if (body?.run_id !== runId) {
        reject(res, 403, 'run-mismatch')
        return
      }
      if (body?.session_id && agent !== null && body.session_id !== agent.id) {
        reject(res, 409, 'session-mismatch')
        return
      }
    }
    if (agent === null) {
      state.delivery_errors += 1
      reject(res, 409, 'agent-not-bound')
      return
    }
    // A status request must never wake a deliberate input wait.  The Python
    // supervisor suppresses pings while awaiting; this is the fail-safe.
    if (waiter !== null) {
      reject(res, 409, 'awaiting-followup')
      return
    }

    const message = textOfContent(JSON.parse(raw)?.message)
    if (message.length === 0) {
      reject(res, 400, 'empty-message')
      return
    }

    // The steering text is supplied by the supervisor, not by the model.
    // Keep it bounded and prefix it so the worker can recognise the source.
    const text = `[dsh-heartbeat status check] ${message.slice(0, 4000)}`
    try {
      agent.steer({
        content: [{ type: 'text', text }],
        source: { kind: 'dsh-heartbeat' },
      })
    } catch (error) {
      state.delivery_errors += 1
      publish({ state: 'delivery-error', last_ping: { error: String(error?.message ?? error) } })
      reject(res, 503, 'steer-failed')
      return
    }
    state.pings += 1
    state.last_ping = {
      at: new Date().toISOString(),
      delivered: true,
      session_id: agent.id,
      agent_status: agent.status ?? null,
    }
    publish({ state: 'bound', last_ping: state.last_ping })
    accept(res, {
      ok: true,
      queued: true,
      // A queued steering item is a transport acknowledgement only.
      worker_response: false,
      session_id: agent.id,
      agent_status: agent.status ?? null,
      ping_count: state.pings,
    })
  }

  const handleFollowup = async (req, res, raw) => {
    let body
    try {
      body = JSON.parse(raw)
    } catch {
      reject(res, 400, 'invalid-json')
      return
    }
    if (runId !== null && body?.run_id !== runId) {
      reject(res, 403, 'run-mismatch')
      return
    }
    if (agent === null) {
      reject(res, 409, 'agent-not-bound')
      return
    }
    if (body?.session_id && body.session_id !== agent.id) {
      reject(res, 409, 'session-mismatch')
      return
    }
    const followupId = typeof body?.ping_id === 'string' ? body.ping_id : ''
    if (followupId.length === 0 || followupId.length > 200) {
      reject(res, 400, 'followup-id-invalid')
      return
    }
    if (seenFollowups.has(followupId)) {
      reject(res, 409, 'duplicate-delivery')
      return
    }
    const message = textOfContent(body?.message)
    if (message.length === 0) {
      reject(res, 400, 'empty-message')
      return
    }
    if (message.length > MAX_FOLLOWUP_CHARS) {
      reject(res, 413, 'message-too-long')
      return
    }
    seenFollowups.add(followupId)
    if (seenFollowups.size > 512) {
      const oldest = seenFollowups.values().next().value
      if (oldest !== undefined) seenFollowups.delete(oldest)
    }
    try {
      if (waiter !== null) {
        const entry = waiter
        const acknowledged = deliverToWaiter(entry, message, followupId)
        await acknowledged
        accept(res, {
          ok: true,
          queued: true,
          kind: 'followup',
          delivered: 'awaiting-turn',
          worker_response: false,
          session_id: agent.id,
          agent_status: agent.status ?? null,
          followup_id: followupId,
        })
        return
      }
      // No explicit wait right now.  A running turn can still accept a steer
      // at its next step boundary; a closing/idle run cannot.
      if (turnStopping || agent.status !== 'running') {
        seenFollowups.delete(followupId)
        reject(res, 409, turnStopping ? 'followup-window-closing' : 'not-awaiting')
        return
      }
      steer(message)
      state.followups_delivered += 1
      state.last_followup = {
        at: new Date().toISOString(),
        followup_id: followupId,
        chars: message.length,
        session_id: agent.id,
      }
      publish({
        state: 'bound',
        followups_delivered: state.followups_delivered,
        last_followup: state.last_followup,
      })
      accept(res, {
        ok: true,
        queued: true,
        kind: 'followup',
        delivered: 'steered',
        worker_response: false,
        session_id: agent.id,
        agent_status: agent.status ?? null,
        followup_id: followupId,
      })
    } catch (error) {
      seenFollowups.delete(followupId)
      state.delivery_errors += 1
      publish({ state: 'delivery-error', last_ping: { error: String(error?.message ?? error) } })
      reject(res, 503, 'followup-failed')
    }
  }

  const handler = (req, res) => {
    if (closed) {
      reject(res, 503, 'closed')
      return
    }
    if (req.headers.origin) {
      reject(res, 403, 'origin-not-allowed')
      return
    }
    const supplied = req.headers['x-dsh-heartbeat-token']
    if (!tokensEqual(supplied, token)) {
      reject(res, 401, 'unauthorized')
      return
    }
    if (req.method !== 'POST' || (req.url !== '/ping' && req.url !== '/followup')) {
      if (req.method === 'GET' && req.url === '/health') {
        accept(res, {
          ok: true,
          bound: agent !== null,
          session_id: agent?.id ?? null,
          agent_status: agent?.status ?? null,
          pings: state.pings,
          awaiting_input: waiter !== null,
          followups_delivered: state.followups_delivered,
        })
        return
      }
      reject(res, 404, 'not-found')
      return
    }

    let raw = ''
    req.setEncoding('utf8')
    req.on('data', (chunk) => {
      raw += chunk
      if (raw.length > MAX_BODY) {
        reject(res, 413, 'body-too-large')
        req.destroy()
      }
    })
    req.on('end', () => {
      if (res.writableEnded) return
      if (!raw) {
        reject(res, 400, 'empty-body')
        return
      }
      try {
        JSON.parse(raw)
      } catch {
        reject(res, 400, 'invalid-json')
        return
      }
      try {
        if (req.url === '/followup') {
          handleFollowup(req, res, raw).catch((error) => {
            state.delivery_errors += 1
            publish({ state: 'delivery-error', last_ping: { error: String(error?.message ?? error) } })
            if (!res.writableEnded) reject(res, 500, 'internal-error')
          })
        } else {
          handlePing(req, res, raw)
        }
      } catch (error) {
        state.delivery_errors += 1
        publish({ state: 'delivery-error', last_ping: { error: String(error?.message ?? error) } })
        reject(res, 500, 'internal-error')
      }
    })
    req.on('error', () => {
      if (!res.writableEnded) reject(res, 400, 'request-error')
    })
  }

  publish({ state: 'listening' })
  server = createServer(handler)
  server.on('error', (error) => {
    state.state = 'server-error'
    state.error = String(error?.message ?? error)
    try {
      publish()
    } catch {
      // The supervisor will fail with control_not_ready.
    }
  })
  server.listen(0, HOST, () => {
    const address = server.address()
    port = typeof address === 'object' && address ? address.port : null
    // Do not keep the one-shot dsh process alive after the agent finishes.
    server.unref()
    publish({ state: agent === null ? 'listening' : 'bound', port })
  })

  ctx.effect(() => () => {
    closed = true
    if (waiter !== null) settleWaiter(waiter, null)
    try {
      server?.closeAllConnections?.()
      server?.close()
    } catch {
      // best effort during teardown
    }
    try {
      publish({ state: 'closed', closed_at: new Date().toISOString(), port })
    } catch {
      // the run directory may already be gone
    }
    try {
      rmSync(`${endpointFile}.${process.pid}.tmp`, { force: true })
    } catch {
      // best effort
    }
  })
}
