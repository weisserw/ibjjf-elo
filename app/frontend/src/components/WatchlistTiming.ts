const MINUTE_MS = 60 * 1000

function remainingTime(localDate: string, localTime: string | null, now: number) {
  if (!localTime) return NaN
  const [year, month, day] = localDate.split('-').map(Number)
  const [hour, minute] = localTime.split(':').map(Number)
  if (![year, month, day, hour, minute].every(Number.isFinite)) return NaN
  return new Date(year, month - 1, day, hour, minute).getTime() - now
}

export function watchMatchOverdue(localDate: string, localTime: string | null, now: number) {
  // Tournament timezones are unknown; a large delay may be a viewer clock offset.
  return remainingTime(localDate, localTime, now) < -30 * MINUTE_MS
}

export function watchMatchUrgency(localDate: string, localTime: string | null, now: number, suppressed = false) {
  if (suppressed) return ''
  const remaining = remainingTime(localDate, localTime, now)
  if (!Number.isFinite(remaining) || remaining < -30 * MINUTE_MS || remaining > 25 * MINUTE_MS) return ''
  return remaining <= 10 * MINUTE_MS ? 'watch-imminent' : 'watch-soon'
}
