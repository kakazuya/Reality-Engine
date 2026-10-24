import { expect, test } from 'claude-code/testing'

import { NOW, encodeBase64 } from './fixtures'
import {
  EMPTY_COUNTS,
  advanceSpark,
  decodeBase64,
  emptyScan,
  metricsOf,
  pruneScans,
  resumeEvents,
  scanEvents,
  touchEvents,
} from './events'

const encoder = new TextEncoder()

function bytes(text: string): Uint8Array {
  return encoder.encode(text)
}

function concat(a: Uint8Array, b: Uint8Array): Uint8Array {
  const joined = new Uint8Array(a.length + b.length)
  joined.set(a, 0)
  joined.set(b, a.length)
  return joined
}

test('a partial trailing line waits for the next read and is counted once', () => {
  const complete = [
    '{"type":"tool_call","tool":"read"}',
    '{"type":"status","phase":"step_end","usage":{"outputTokens":100}}',
  ].join('\n')
  const partial = '{"type":"tool_call","tool":"wr'
  const first = bytes(`${complete}\n${partial}`)

  const once = scanEvents(first, 0, EMPTY_COUNTS)
  expect(once.counts.toolCalls).toBe(1)
  expect(once.counts.modelSteps).toBe(1)
  expect(once.counts.outputTokens).toBe(100)
  expect(once.counts.lastTool).toBe('read')
  expect(once.offset).toBe(bytes(`${complete}\n`).length)
  expect(once.lines).toBe(2)

  const rest = bytes(
    'ite","input":{"file_path":"a.ts"}}\n' +
      '{"type":"tool_call","tool":"pwsh","input":{"description":"npm test"}}\n',
  )
  const all = concat(first, rest)
  const twice = scanEvents(all, once.offset, once.counts)

  expect(twice.counts.toolCalls).toBe(3)
  expect(twice.counts.recentFiles).toEqual(['a.ts'])
  expect(twice.counts.lastTool).toBe('pwsh')
  expect(twice.counts.lastToolTarget).toBe('npm test')
  expect(twice.counts.byTool['write']).toBe(1)
  expect(twice.counts.byTool['pwsh']).toBe(1)
  expect(twice.offset).toBe(all.length)
})

test('only complete lines are consumed when no newline has arrived yet', () => {
  const partial = bytes('{"type":"tool_call","tool":"pwsh"}')
  const result = scanEvents(partial, 0, EMPTY_COUNTS)
  expect(result.counts.toolCalls).toBe(0)
  expect(result.offset).toBe(0)
})

test('output tokens and model steps accept both usage spellings', () => {
  const text = [
    '{"type":"status","phase":"step_end","usage":{"outputTokens":1000}}',
    '{"type":"status","phase":"step_end","usage":{"output_tokens":2600}}',
    '{"type":"status","phase":"step_start"}',
  ].join('\n')
  const result = scanEvents(bytes(`${text}\n`), 0, EMPTY_COUNTS)
  expect(result.counts.modelSteps).toBe(2)
  expect(result.counts.outputTokens).toBe(3600)
})

test('a shorter file resets the counts instead of resuming past its end', () => {
  const longer = bytes(
    [
      '{"type":"tool_call","tool":"read"}',
      '{"type":"tool_call","tool":"write","input":{"file_path":"a.ts"}}',
      '',
    ].join('\n'),
  )
  const first = resumeEvents(undefined, longer, NOW)
  expect(first.toolCalls).toBe(2)
  expect(first.recentFiles).toEqual(['a.ts'])

  const shorter = resumeEvents(
    first,
    bytes('{"type":"tool_call","tool":"grep"}\n'),
    NOW,
  )
  expect(shorter.toolCalls).toBe(1)
  expect(shorter.lastTool).toBe('grep')
  expect(shorter.recentFiles).toEqual([])
  expect(shorter.offset).toBe(bytes('{"type":"tool_call","tool":"grep"}\n').length)
})

test('resume parses only the new tail; the sparkline ages one bucket per minute', () => {
  const firstText = '{"type":"tool_call","tool":"read"}\n'
  const first = resumeEvents(undefined, bytes(firstText), NOW)
  expect(first.toolCalls).toBe(1)
  expect(first.spark.every(value => value === 0)).toBe(true)

  const second = resumeEvents(
    first,
    bytes(`${firstText}{"type":"tool_call","tool":"grep"}\n`),
    NOW + 60_000,
  )
  expect(second.toolCalls).toBe(2)
  expect(second.spark[29]).toBe(1)
  expect(second.spark[28]).toBe(0)
})

test('no new bytes only ages the sparkline window', () => {
  const spark = Array.from({ length: 30 }, () => 0)
  spark[28] = 9
  spark[29] = 4
  const scan = {
    ...emptyScan(NOW),
    toolCalls: 7,
    spark,
  }
  const touched = touchEvents(scan, NOW + 60_000)
  expect(touched.toolCalls).toBe(7)
  expect(touched.spark[27]).toBe(9)
  expect(touched.spark[28]).toBe(4)
  expect(touched.spark[29]).toBe(0)
  expect(touched.sparkAt).toBe(NOW + 60_000)
})

test('the sparkline shifts and drops in one move past its window', () => {
  const spark = Array.from({ length: 30 }, (_, index) => index + 1)
  const one = advanceSpark(spark, NOW, NOW + 60_000, 2)
  expect(one.spark).toHaveLength(30)
  expect(one.spark[27]).toBe(29)
  expect(one.spark[28]).toBe(30)
  expect(one.spark[29]).toBe(2)

  const gone = advanceSpark(spark, NOW, NOW + 31 * 60_000, 5)
  expect(gone.spark.filter(value => value > 0)).toEqual([5])
})

test('15 second ticks keep the minute boundary instead of drifting', () => {
  const first = advanceSpark(undefined, undefined, NOW, 1)
  expect(first.sparkAt).toBe(NOW)

  const second = advanceSpark(first.spark, first.sparkAt, NOW + 15_000, 1)
  expect(second.sparkAt).toBe(NOW)
  expect(second.spark[29]).toBe(2)

  const third = advanceSpark(second.spark, second.sparkAt, NOW + 75_000, 1)
  expect(third.sparkAt).toBe(NOW + 60_000)
  expect(third.spark[28]).toBe(2)
  expect(third.spark[29]).toBe(1)
})

test('base64 decodes to the same bytes and metrics flatten the scan', () => {
  const text = '{"type":"tool_call","tool":"read"}\n'
  const decoded = decodeBase64(encodeBase64(text))
  expect(Array.from(decoded)).toEqual(Array.from(bytes(text)))

  const scan = resumeEvents(
    undefined,
    bytes(
      [
        '{"type":"tool_call","tool":"read"}',
        '{"type":"tool_call","tool":"write","input":{"file_path":"a.ts"}}',
        '{"type":"status","phase":"step_end","usage":{"outputTokens":500}}',
        '',
      ].join('\n'),
    ),
    NOW,
  )
  const metrics = metricsOf(scan)
  expect(metrics.toolCalls).toBe(2)
  expect(metrics.modelSteps).toBe(1)
  expect(metrics.outputTokens).toBe(500)
  expect(metrics.fileWrites).toBe(1)
  expect(metrics.lastTool).toBe('write')
  expect(metrics.byTool).toEqual({ read: 1, write: 1 })
})

test('the scan cache prunes jobs outside the current window', () => {
  const scan = emptyScan(NOW)
  const pruned = pruneScans(
    { jobs: { a: scan, b: scan } },
    new Set(['a']),
  )
  expect(Object.keys(pruned.jobs)).toEqual(['a'])
})
