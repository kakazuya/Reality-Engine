import { expect, mock, test } from 'claude-code/testing'

import { STATUS } from './palette'
import {
  APP_START,
  CANCELLED_ID,
  DATA_FINISHED_ID,
  DATA_RUNNING_ID,
  FAILED_TODAY_ID,
  FINISHED_ID,
  FIXTURE_ENTRIES,
  FIXTURE_FILES,
  FIXTURE_ROOT,
  NOW,
  RECENT_ENTRY,
  RECENT_ID,
  RUNNING_ID,
  STALLED_ID,
  byteLength,
  encodeBase64,
} from './fixtures'

const PANE = {
  plugin: 'dsh-workers',
  component: 'Pane',
  requestId: 'dsh-workers',
  props: {
    title: 'DeepSeek workers',
    isFocused: false,
    bodyColumns: 100,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const BAND = {
  plugin: 'dsh-workers',
  component: 'AbovePrompt',
  requestId: 'dsh-workers-band',
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 6,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 6 },
    view: {},
  },
} as const

// The engine normalises a path before raising fs.list / fs.read.
const pathKey = (path: string): string => path.replace(/\\/g, '/')

function textsOf(
  elements: Array<{ text: string }>,
): string[] {
  return elements.map(element => element.text)
}

type TestOn = Parameters<typeof mock.clock>[0]
type FixtureEntry = {
  name: string
  kind: 'dir'
  size: number
  mtimeMs: number
  isLink: boolean
}

/**
 * The fixture filesystem for one test, with the jobs folder under the test's
 * control: `entries` is read on every list, so a test can make a job appear
 * midway, and `isBroken` makes reads fail on demand.
 */
function wire(
  on: TestOn,
  entries: () => readonly FixtureEntry[],
  options: { isBroken?: () => boolean; isPlaced?: boolean } = {},
): { statuses: Array<string | undefined>; opened: string[] } {
  const statuses: Array<string | undefined> = []
  const opened: string[] = []
  const isBroken = options.isBroken ?? (() => false)
  const isPlaced = options.isPlaced ?? true

  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('command.register', (_, e) => ({ value: { command: e.name } }))
  on('ui.open', (_, e) => {
    opened.push(e.id)
    return isPlaced
      ? { value: { isPlaced: true as const } }
      : { value: { isPlaced: false as const, reason: 'not placed' } }
  })
  on('ui.status', (_, e) => {
    statuses.push(e.text)
    return { value: undefined }
  })
  on('fs.list', () => {
    if (isBroken()) throw new Error('EIO: fixtures unreadable')
    return { value: [...entries()] }
  })
  on('fs.read', (_, e) => {
    const text = FIXTURE_FILES[pathKey(e.path)]
    if (text === undefined) return { deny: 'ENOENT' }
    return e.as === 'bytes'
      ? { value: { base64: encodeBase64(text) } }
      : { value: text }
  })
  on('fs.stat', (_, e) => {
    const text = FIXTURE_FILES[pathKey(e.path)]
    if (text === undefined) return { deny: 'ENOENT' }
    return {
      value: {
        kind: 'file' as const,
        size: byteLength(text),
        mtimeMs: NOW,
        isLink: false,
      },
    }
  })
  return { statuses, opened }
}

test(
  'the rail draws running rows, chips and one expandable detail at a time',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })
    const statuses: Array<string | undefined> = []

    on('session.start', (_, e) => ({ cwd: e.cwd }))
    on('command.register', (_, e) => ({ value: { command: e.name } }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('ui.status', (_, e) => {
      statuses.push(e.text)
      return { value: undefined }
    })
    on('fs.list', (_, e) => ({
      value: pathKey(e.path) === FIXTURE_ROOT ? [...FIXTURE_ENTRIES] : [],
    }))
    on('fs.read', (_, e) => {
      const text = FIXTURE_FILES[pathKey(e.path)]
      if (text === undefined) return { deny: 'ENOENT' }
      return e.as === 'bytes'
        ? { value: { base64: encodeBase64(text) } }
        : { value: text }
    })
    on('fs.stat', (_, e) => {
      const text = FIXTURE_FILES[pathKey(e.path)]
      if (text === undefined) return { deny: 'ENOENT' }
      return {
        value: {
          kind: 'file' as const,
          size: byteLength(text),
          mtimeMs: NOW,
          isLink: false,
        },
      }
    })

    await $.session.start({
      cwd: 'C:/',
      surface: 'terminal',
      isInteractive: true,
    })
    expect(statuses.at(-1)).toBe('dsh: 2 running, 1 stalled')
    // Move on to the fixtures' reference moment; the 15 s timer keeps the
    // view fresh across it.
    await clock.set(NOW)

    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({
        ...PANE,
        surface,
        viewport: { columns: 100, rows: 50 },
      })

      const texts = textsOf(await ui.findAll({ type: 'Text' }))
      const joined = texts.join('\n')
      expect(joined).toContain('● 2 running')
      expect(joined).toContain('◐ 1 stalled')
      expect(joined).toContain('✕ 3 failed')
      expect(joined).toContain('✓ 3 finished')
      // The chips carry the v3 phase colours, dark text on the bright fill.
      const runningChip = await ui.find({ type: 'Text', text: '● 2 running' })
      expect(runningChip?.props.backgroundColor).toBe(STATUS.success.bg)
      expect(runningChip?.props.color).toBe(STATUS.success.fg)
      // The mix bar runs each phase across its gradient.
      const backgrounds = (await ui.findAll({ type: 'Text' })).map(
        text => text.props.backgroundColor,
      )
      expect(backgrounds).toContain(STATUS.success.light)
      expect(backgrounds).toContain(STATUS.info.deep)
      expect(joined).toContain('Running')
      expect(joined).toContain('Fix the resource watchdog')
      expect(joined).toContain('Chunk every FY26 annual report')
      expect(joined).toContain('insider_trades')
      // Live duration on the running row, right aligned.
      expect(joined).toContain('20m 00s')
      expect(joined).toContain('50m 00s')

      // Finished stays collapsed until its header is pressed.
      const finishedHeader = await ui.find({ type: 'Button', key: 'finished' })
      expect(finishedHeader?.text).toBe('Finished 7 ▸')
      expect(joined).not.toContain('Rebuild search index')

      // Rows are separated by thin dividers.
      const dividers = await ui.findAll({ type: 'Text', text: /^─+$/ })
      expect(dividers.length).toBeGreaterThanOrEqual(3)

      await ui.press({ key: RUNNING_ID })

      const expanded = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
      expect(expanded).toContain('Details.')
      expect(expanded).toContain('OUTPUT')
      expect(expanded).toContain('⚙ pwsh → npm test')
      expect(expanded).toContain('tools')
      expect(expanded).toContain('3.6k')
      expect(expanded).toContain('1h40 left')
      expect(expanded).toContain('TOOLS')
      expect(expanded).toContain('20261024T114000Z-aaaaaaaa')
      expect(expanded).toContain('workspace C:\\IDM-worktrees\\aaaa')

      const lease = await ui.find({ type: 'Text', text: /1h40 left/ })
      expect(lease?.props.color).toBe('success')
      const svgs = await ui.findAll({ type: 'Svg' })
      if (surface === 'terminal') {
        expect(svgs).toHaveLength(0)
        expect(expanded).toContain('█')
      } else {
        expect(svgs.length).toBeGreaterThan(0)
        expect(
          svgs.some(svg => String(svg.props.alt).includes('lease remaining')),
        ).toBe(true)
      }

      // One card at a time: expanding the stalled row collapses the first.
      await ui.press({ key: STALLED_ID })
      const stalledTexts = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
      expect(stalledTexts).not.toContain('Details.')
      expect(stalledTexts).toContain('10m left')
      const stalledLease = await ui.find({ type: 'Text', text: /10m left/ })
      expect(stalledLease?.props.color).toBe('error')
      const outputs = await ui.findAll({ type: 'Text', text: 'OUTPUT' })
      expect(outputs).toHaveLength(1)

      await ui.unmount()
    }

    const run = await $.command.run({
      command: 'dsh-workers',
      args: '',
      origin: { kind: 'composer' },
      presentation: { isFullscreen: true, columns: 120 },
    })
    expect(run.text).toBe('DeepSeek workers pane opened.')
  },
)

test(
  'finished opens into owner-session groups and its rows expand in place',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })

    on('session.start', (_, e) => ({ cwd: e.cwd }))
    on('command.register', (_, e) => ({ value: { command: e.name } }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('ui.status', () => ({ value: undefined }))
    on('fs.list', (_, e) => ({
      value: pathKey(e.path) === FIXTURE_ROOT ? [...FIXTURE_ENTRIES] : [],
    }))
    on('fs.read', (_, e) => {
      const text = FIXTURE_FILES[pathKey(e.path)]
      if (text === undefined) return { deny: 'ENOENT' }
      return e.as === 'bytes'
        ? { value: { base64: encodeBase64(text) } }
        : { value: text }
    })
    on('fs.stat', (_, e) => {
      const text = FIXTURE_FILES[pathKey(e.path)]
      if (text === undefined) return { deny: 'ENOENT' }
      return {
        value: {
          kind: 'file' as const,
          size: byteLength(text),
          mtimeMs: NOW,
          isLink: false,
        },
      }
    })

    await $.session.start({
      cwd: 'C:/',
      surface: 'terminal',
      isInteractive: true,
    })
    await clock.set(NOW)

    const ui = await $.ui.mount({
      ...PANE,
      surface: 'desktop',
      viewport: { columns: 100, rows: 50 },
    })

    await ui.press({ key: 'finished' })

    const openTexts = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
    expect(openTexts).toContain('beta · 23 Oct 22:15Z · 4')
    expect(openTexts).toContain('alpha · 24 Oct 07:03Z · 3')
    expect(openTexts).toContain('Rebuild search index')
    expect(openTexts).toContain('market_raw_exchange')
    expect(openTexts).toContain('nifty_index')

    // Groups newest first; rows newest first inside a group.
    const index = (needle: string) => openTexts.indexOf(needle)
    expect(index('beta · 23 Oct 22:15Z')).toBeLessThan(
      index('alpha · 24 Oct 07:03Z'),
    )
    expect(index('Cancelled experiment')).toBeLessThan(
      index('Backfill price history'),
    )
    expect(index('Backfill price history')).toBeLessThan(
      index('bse_announcements'),
    )
    expect(index('market_raw_exchange')).toBeLessThan(
      index('Rebuild search index'),
    )

    await ui.press({ key: FINISHED_ID })
    const detail = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
    expect(detail).toContain('exit 0')
    expect(detail).toContain('ended 1h ago')
    expect(detail).toContain('workspace C:\\IDM-worktrees\\cccc')
    expect(detail).toContain('session alpha · 24 Oct 07:03Z')
    expect(detail).toContain('last tool')
    expect(detail).toContain('⎇ dsh/rebuild-search')

    await ui.press({ key: 'finished' })
    const closed = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
    expect(closed).not.toContain('Rebuild search index')
    const closedHeader = await ui.find({ type: 'Button', key: 'finished' })
    expect(closedHeader?.text).toBe('Finished 7 ▸')

    await ui.unmount()
  },
)

test(
  'the terminal fallback draws its own bars and never an Svg',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })

    on('session.start', (_, e) => ({ cwd: e.cwd }))
    on('command.register', (_, e) => ({ value: { command: e.name } }))
    on('ui.open', () => ({ value: { isPlaced: true } }))
    on('ui.status', () => ({ value: undefined }))
    on('fs.list', (_, e) => ({
      value: pathKey(e.path) === FIXTURE_ROOT ? [...FIXTURE_ENTRIES] : [],
    }))
    on('fs.read', (_, e) => {
      const text = FIXTURE_FILES[pathKey(e.path)]
      if (text === undefined) return { deny: 'ENOENT' }
      return e.as === 'bytes'
        ? { value: { base64: encodeBase64(text) } }
        : { value: text }
    })
    on('fs.stat', (_, e) => {
      const text = FIXTURE_FILES[pathKey(e.path)]
      if (text === undefined) return { deny: 'ENOENT' }
      return {
        value: {
          kind: 'file' as const,
          size: byteLength(text),
          mtimeMs: NOW,
          isLink: false,
        },
      }
    })

    await $.session.start({
      cwd: 'C:/',
      surface: 'terminal',
      isInteractive: true,
    })
    await clock.set(NOW)

    const ui = await $.ui.mount({
      ...PANE,
      surface: 'terminal',
      props: { ...PANE.props, bodyColumns: 40 },
      viewport: { columns: 40, rows: 40 },
    })

    await ui.press({ key: RUNNING_ID })
    const texts = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
    expect(texts).toContain('Fix the resource watchdog')
    expect(texts).toContain('1h40 left')
    expect(texts).toContain('█')
    expect(texts).toContain('░')
    expect(await ui.findAll({ type: 'Svg' })).toHaveLength(0)

    await ui.unmount()
  },
)

test(
  'idle until a job starts after the session: no pane, no band, no status line',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })
    let entries: readonly FixtureEntry[] = []
    const { statuses, opened } = wire(on, () => entries)
    // Stands for the engine's own band, drawn only where the mod passes.
    on('ui.render', { component: 'AbovePrompt' }, ($, e) => {
      const { Text } = $.ui.resolve(e)
      return <Text>engine band</Text>
    })

    await $.session.start({
      cwd: 'C:/',
      surface: 'desktop',
      isInteractive: true,
    })
    // An empty jobs folder: nothing started since the session did.
    expect(opened).toEqual([])
    expect(statuses.every(text => text === undefined)).toBe(true)

    const band = await $.ui.mount({
      ...BAND,
      surface: 'desktop',
      viewport: { columns: 100, rows: 40 },
    })
    const idle = textsOf(await band.findAll({ type: 'Text' })).join('\n')
    expect(idle).toContain('engine band')
    expect(idle).not.toContain('Fix the resource watchdog')

    // A worker starts after the session began: the next 15 s tick shows it.
    entries = [...FIXTURE_ENTRIES, RECENT_ENTRY]
    await clock.advance(15_000)

    expect(statuses.at(-1)).toBe('dsh: 3 running, 1 stalled')
    const shown = textsOf(await band.findAll({ type: 'Text' })).join('\n')
    expect(shown).toContain('Smoke the reconcile pass')
    expect(shown).toContain('Fix the resource watchdog')
    expect(shown).not.toContain('Mid-write job')
    expect(shown).not.toContain('engine band')
    expect(opened).toEqual([])

    await band.unmount()
  },
)

test(
  'the above-prompt band is one coloured line per running job',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })
    wire(on, () => FIXTURE_ENTRIES)

    await $.session.start({
      cwd: 'C:/',
      surface: 'desktop',
      isInteractive: true,
    })
    await clock.set(NOW)

    for (const surface of ['terminal', 'desktop', 'mobile'] as const) {
      const band = await $.ui.mount({
        ...BAND,
        surface,
        viewport: { columns: 100, rows: 40 },
      })
      const texts = textsOf(await band.findAll({ type: 'Text' })).join('\n')
      expect(texts).toContain('Fix the resource watchdog')
      expect(texts).toContain('Chunk every FY26 annual report')
      expect(texts).toContain('insider_trades')
      expect(texts).toContain('20m 00s')
      expect(texts).toContain('idle 5m')
      expect(texts).toContain('1h40 left')

      const glyphs = await band.findAll({ type: 'Text', text: '●' })
      expect(glyphs.length).toBeGreaterThan(0)
      expect(
        glyphs.every(glyph => glyph.props.color === STATUS.success.fill),
      ).toBe(true)
      const stalled = await band.findAll({ type: 'Text', text: '◐' })
      expect(stalled[0]?.props.color).toBe(STATUS.warning.fill)

      await band.unmount()
    }
  },
)

test(
  '/dsh-workers answers with a Markdown summary where no pane can be placed',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })
    wire(on, () => FIXTURE_ENTRIES, { isPlaced: false })

    await $.session.start({
      cwd: 'C:/',
      surface: 'mobile',
      isInteractive: true,
    })
    await clock.set(NOW)

    const run = await $.command.run({
      command: 'dsh-workers',
      args: '',
      origin: { kind: 'composer' },
      presentation: { isFullscreen: false, columns: 60 },
    })
    const text = run.text ?? ''
    expect(text).toContain('**DeepSeek workers** — 2 running · 1 stalled')
    expect(text).toContain(
      '- ● **Fix the resource watchdog** — 20m 00s · 4 tools · idle 5m · lease 1h40 left',
    )
    expect(text).toContain('- ◐ **Chunk every FY26 annual report**')
    expect(text).toContain('lease 10m left')
    expect(text).toContain('insider_trades')
    expect(text).toContain('2 finished · 2 failed today')
  },
)

test(
  'an unreadable jobs folder is logged, not thrown, and keeps the last good view',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    const clock = mock.clock(on, { now: APP_START })
    let isBroken = false
    const { statuses } = wire(on, () => FIXTURE_ENTRIES, {
      isBroken: () => isBroken,
    })

    await $.session.start({
      cwd: 'C:/',
      surface: 'desktop',
      isInteractive: true,
    })
    await clock.set(NOW)

    const ui = await $.ui.mount({
      ...PANE,
      surface: 'desktop',
      viewport: { columns: 100, rows: 50 },
    })
    expect(textsOf(await ui.findAll({ type: 'Text' })).join('\n')).toContain(
      'Fix the resource watchdog',
    )

    // The next tick reads a broken folder: the view stays as it was, the pane
    // names the failure and the status line marks it stale.
    isBroken = true
    await clock.advance(15_000)
    const after = textsOf(await ui.findAll({ type: 'Text' })).join('\n')
    expect(after).toContain('Fix the resource watchdog')
    expect(after).toContain('cannot read')
    expect(statuses.at(-1)).toContain('stale')

    await ui.unmount()
  },
)

test(
  'a broken jobs folder never throws out of session.start or /dsh-workers',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    mock.clock(on, { now: NOW })
    const { statuses, opened } = wire(on, () => FIXTURE_ENTRIES, {
      isBroken: () => true,
      isPlaced: false,
    })

    const started = await $.session.start({
      cwd: 'C:/',
      surface: 'mobile',
      isInteractive: true,
    })
    expect(started.cwd).toBe('C:/')
    expect(opened).toEqual([])
    expect(statuses.every(text => text === undefined)).toBe(true)

    const run = await $.command.run({
      command: 'dsh-workers',
      args: '',
      origin: { kind: 'composer' },
      presentation: { isFullscreen: false, columns: 60 },
    })
    expect(run.text).toContain('No workers running.')
    expect(run.text).toContain('0 finished · 0 failed today')
  },
)
