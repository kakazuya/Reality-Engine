import { expect, mock, test } from 'claude-code/testing'

import { FIXTURE_ENTRIES, FIXTURE_FILES, FIXTURE_ROOT, NOW } from './fixtures'

const PANE = {
  plugin: 'dsh-workers',
  component: 'Pane',
  requestId: 'dsh-workers',
  props: {
    title: 'DeepSeek workers',
    isFocused: false,
    bodyColumns: 40,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

// The engine normalises a path before raising fs.list / fs.read.
const pathKey = (path: string): string => path.replace(/\\/g, '/')

test(
  'the pane draws fixture jobs, header, lease colours and status line',
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
    on('fs.read', (_, e) => ({
      value: FIXTURE_FILES[pathKey(e.path)] ?? '',
    }))

    await $.session.start({
      cwd: 'C:/',
      surface: 'terminal',
      isInteractive: true,
    })
    expect(statuses.at(-1)).toBe('dsh: 1 running, 1 stalled')

    for (const surface of ['terminal', 'desktop'] as const) {
      const ui = await $.ui.mount({
        ...PANE,
        surface,
        viewport: { columns: 40, rows: 30 },
      })

      const header = await ui.find({ type: 'Text', text: /finished today/ })
      expect(header?.text).toContain(
        '1 running · 1 stalled · 1 finished today',
      )

      const texts = (await ui.findAll({ type: 'Text' })).map(
        element => element.text,
      )
      const index = (needle: string) =>
        texts.findIndex(text => text.includes(needle))

      // running, stalled, unreadable; then the newest finished, then failed
      expect(index('Fix the resource watchdog')).toBeLessThan(
        index('Chunk every FY26 annual report'),
      )
      expect(index('Chunk every FY26 annual report')).toBeLessThan(
        index('Mid-write job'),
      )
      expect(index('Mid-write job')).toBeLessThan(
        index('Rebuild search index'),
      )
      expect(index('Rebuild search index')).toBeLessThan(
        index('Backfill price history'),
      )

      expect(texts.some(text => text.includes('tc 3'))).toBe(true)
      expect(texts.some(text => text.includes('unreadable'))).toBe(true)

      const leases = await ui.findAll({ type: 'Text', text: /lease/ })
      expect(
        leases.some(
          row => row.text.includes('10m') && row.props.color === 'error',
        ),
      ).toBe(true)
      expect(
        leases.some(
          row => row.text.includes('50m') && row.props.color === 'error',
        ),
      ).toBe(false)

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
