import { language, t } from '../translate'
import { immatureClass } from '../utils'
import { WatchRow, WatchSide } from './WatchlistShared'

export function watchDay(date: string) {
  const [year, month, day] = date.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(language(), { weekday: 'long' })
}

export function watchTime(time: string | null) {
  if (!time) return t('Time pending')
  const [hour, minute] = time.split(':').map(Number)
  return `${hour % 12 || 12}:${String(minute).padStart(2, '0')}${hour < 12 ? 'am' : 'pm'}`
}

export function watchMatchUrgency(localDate: string, localTime: string | null, now: number) {
  if (!localTime) return ''
  const [year, month, day] = localDate.split('-').map(Number)
  const [hour, minute] = localTime.split(':').map(Number)
  if (![year, month, day, hour, minute].every(Number.isFinite)) return ''
  const scheduledAt = new Date(year, month - 1, day, hour, minute).getTime()
  const remaining = scheduledAt - now
  if (remaining > 25 * 60 * 1000) return ''
  return remaining <= 10 * 60 * 1000 ? 'watch-imminent' : 'watch-soon'
}

export function watchDayGroups(rows: WatchRow[]) {
  const groups = new Map<string, WatchRow[]>()
  for (const row of rows) {
    const date = row.match?.local_date || ''
    groups.set(date, [...(groups.get(date) || []), row])
  }
  return [...groups].sort(([a], [b]) => (a || '9999').localeCompare(b || '9999'))
}

export function watchCountdown(nextAt: number, now: number) {
  const seconds = Math.max(0, Math.ceil((nextAt - now) / 1000))
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
}

export function watchOpponentName(side?: WatchSide) {
  // Keep the source description intact; only the displayed label is simplified.
  return side?.description || !side?.name ? t('TBD') : side.name
}

export function WatchName({ name, profile_url }: { name: string; profile_url: string | null }) {
  return profile_url ? <a href={profile_url} target="_blank" rel="noopener noreferrer">{name}</a> : <span>{name || t('Athlete unavailable')}</span>
}

export function WatchRating({ side }: { side?: WatchSide }) {
  if (!side || side.rating === null) return null
  const immature = immatureClass(side.match_count)
  const provisionalTooltip = immature === 'very-immature'
    ? `${t("Athlete's rating is provisional due to insufficient matches within three years")} (${side.match_count})`
    : `${t("Athlete's rating is semi-provisional due to insufficient matches within three years")} (${side.match_count})`
  return <span className="watch-rating">
    ({Math.round(side.rating)}{immature && <> <span className="has-cursor-pointer" data-tooltip-id="watchlist-rating-tooltip" data-tooltip-content={provisionalTooltip} aria-label={provisionalTooltip}> <span className={`${immature}-bullet`}>{'\u00a0'}</span></span></>})
    {side.win_probability !== null && <> {Math.round(side.win_probability * 100)}%</>}
  </span>
}
