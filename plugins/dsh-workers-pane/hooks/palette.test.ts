import { expect, test } from 'claude-code/testing'

import { STATUS, mixHex } from './palette'

/** WCAG relative luminance of a `#rrggbb` colour. */
function luminance(hex: string): number {
  const clean = hex.replace('#', '')
  const channel = (start: number): number => {
    const value = parseInt(clean.slice(start, start + 2), 16) / 255
    return value <= 0.03928
      ? value / 12.92
      : Math.pow((value + 0.055) / 1.055, 2.4)
  }
  return 0.2126 * channel(0) + 0.7152 * channel(2) + 0.0722 * channel(4)
}

function contrast(a: string, b: string): number {
  const first = luminance(a)
  const second = luminance(b)
  const high = Math.max(first, second)
  const low = Math.min(first, second)
  return (high + 0.05) / (low + 0.05)
}

test('the phase palette is sunset yellow, mango orange and lime green', () => {
  expect(STATUS.success.fill.toLowerCase()).toBe('#ffb627')
  expect(STATUS.success.light.toLowerCase()).toBe('#ffd166')
  expect(STATUS.success.deep.toLowerCase()).toBe('#ff9f1c')

  expect(STATUS.warning.fill.toLowerCase()).toBe('#ff8243')
  expect(STATUS.warning.light.toLowerCase()).toBe('#ffa552')
  expect(STATUS.warning.deep.toLowerCase()).toBe('#ff7518')

  expect(STATUS.info.fill.toLowerCase()).toBe('#9be15d')
  expect(STATUS.info.light.toLowerCase()).toBe('#b8f35a')
  expect(STATUS.info.deep.toLowerCase()).toBe('#32cd32')

  // Failed stays red, cancelled stays grey.
  expect(STATUS.error.fill.toLowerCase()).toBe('#ff5c5c')
  expect(STATUS.muted.fill.toLowerCase()).toBe('#94a3b8')
})

test('every chip and phase colour clears 4.5:1 on the dark card', () => {
  const card = '#0f172a'
  for (const tone of [
    'success',
    'warning',
    'error',
    'info',
    'muted',
  ] as const) {
    const status = STATUS[tone]
    expect(contrast(status.fill, card)).toBeGreaterThanOrEqual(4.5)
    expect(contrast(status.fg, status.bg)).toBeGreaterThanOrEqual(4.5)
  }
})

test('mixHex walks the gradient stops', () => {
  expect(mixHex(STATUS.success.light, STATUS.success.deep, 0)).toBe(
    STATUS.success.light,
  )
  expect(mixHex(STATUS.success.light, STATUS.success.deep, 1)).toBe(
    STATUS.success.deep,
  )
  expect(mixHex('#ffffff', '#000000', 2)).toBe('#000000')
  expect(mixHex('#ffffff', '#000000', -1)).toBe('#ffffff')
})
