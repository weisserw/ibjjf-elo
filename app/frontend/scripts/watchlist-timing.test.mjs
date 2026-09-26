import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import ts from 'typescript'

const source = readFileSync(new URL('../src/components/WatchlistTiming.ts', import.meta.url), 'utf8')
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } })
const { watchMatchOverdue, watchMatchUrgency } = await import(`data:text/javascript;base64,${Buffer.from(outputText).toString('base64')}`)
const date = '2026-09-25'
const start = new Date(2026, 8, 25, 12, 0).getTime()
const minute = 60 * 1000

test('urgency boundaries include exactly 30 minutes late', () => {
  for (const [remaining, expected] of [
    [25 * minute + 1, ''], [25 * minute, 'watch-soon'],
    [10 * minute + 1, 'watch-soon'], [10 * minute, 'watch-imminent'],
    [0, 'watch-imminent'], [-30 * minute, 'watch-imminent'],
    [-30 * minute - 1, ''], [-60 * minute, ''],
  ]) {
    assert.equal(watchMatchUrgency(date, '12:00', start - remaining), expected)
    assert.equal(watchMatchOverdue(date, '12:00', start - remaining), remaining < -30 * minute)
  }
})

test('an overdue first match suppresses later red and yellow matches and clears on refresh', () => {
  const now = start + 31 * minute
  const suppressed = watchMatchOverdue(date, '12:00', now)
  for (const [time, expected] of [['12:35', 'watch-imminent'], ['12:50', 'watch-soon']]) {
    assert.equal(watchMatchUrgency(date, time, now, suppressed), '')
    const refreshedSuppression = watchMatchOverdue(date, '12:35', now)
    assert.equal(watchMatchUrgency(date, time, now, refreshedSuppression), expected)
  }
})

test('unknown and invalid times neither highlight nor suppress other matches', () => {
  for (const time of [null, 'invalid']) {
    assert.equal(watchMatchUrgency(date, time, start), '')
    assert.equal(watchMatchOverdue(date, time, start), false)
  }
  assert.equal(watchMatchUrgency('invalid', '12:00', start), '')
})

test('cutoff uses the full local date across midnight', () => {
  const now = new Date(2026, 8, 26, 0, 1).getTime()
  assert.equal(watchMatchUrgency(date, '23:30', now), '')
  assert.equal(watchMatchOverdue(date, '23:30', now), true)
  assert.equal(watchMatchUrgency('2026-09-26', '00:10', now), 'watch-imminent')
})
