import { expect, mock, test } from 'claude-code/testing'

import {
  CANCELLED_ID,
  DATA_FINISHED_ID,
  DATA_RUNNING_ID,
  FAILED_TODAY_ID,
  FINISHED_ID,
  FIXTURE_ENTRIES,
  FIXTURE_FILES,
  FIXTURE_ROOT,
  NOW,
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

// The engine normalises a path before raising fs.list / fs.read.
const pathKey = (path: string): string => path.replace(/\\/g, '/')

function textsOf(
  elements: Array<{ text: string }>,
): string[] {
  return elements.map(element => element.text)
}

test(
  'the rail draws running rows, chips and one expandable detail at a time',
  { options: { jobsRoot: FIXTURE_ROOT } },
  async ($, on) => {
    mock.clock(on, { now: NOW })
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
    mock.clock(on, { now: NOW })

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
    mock.clock(on, { now: NOW })

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
