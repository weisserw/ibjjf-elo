import { t, translationKeys } from '../translate'

export interface WatchAthlete {
  id: string
  ibjjf_id: string | null
  name: string
  profile_url: string | null
  trackable: boolean
  registrations?: { team: string; event_id: string; tournament: string }[]
}
export interface WatchTournament {
  event_id: string
  name: string
  start_date: string | null
  end_date: string | null
  selectable: boolean
  registration_ready: boolean
  is_kids_tournament: boolean
  state?: string
  refreshing?: boolean
  fetched_at?: string | null
}
export interface WatchSelection {
  id: string
  selection: { event_ids: string[]; athlete_ids: string[] }
  expires_at: string
  tournaments: WatchTournament[]
  athletes: WatchAthlete[]
}
export interface WatchSide {
  name: string | null
  description: string | null
  profile_url: string | null
  rating: number | null
  match_count: number | null
  win_probability: number | null
}
export interface WatchRow {
  athlete: WatchAthlete
  state: string
  match: { local_date: string; local_time: string | null; mat: number; division: string; bracket_category?: string | null; event_id: string } | null
  competitor?: WatchSide
  opponent?: WatchSide
}
export interface WatchData extends WatchSelection {
  rows: WatchRow[]
  poll_after_seconds: number
}

const errors: Record<string, translationKeys> = {
  watchlist_capacity_reached: 'Watchlist capacity has been reached. Please try again later.',
  selection_required: 'Select at least one tournament and athlete.',
  selection_too_large: 'Select up to 10 tournaments and 200 athletes.',
  invalid_tournaments: 'A selected tournament is no longer available. Update your selection.',
  athletes_no_longer_eligible: 'Some athletes are no longer eligible. Update your selection.',
  watchlist_expired: 'This watchlist has expired or is unavailable.',
  watchlist_unavailable: 'This watchlist has expired or is unavailable.',
}
export class WatchError extends Error {
  constructor(public status: number, public code: string) { super(code) }
}
export const errorText = (error: unknown) => t(
  error instanceof WatchError && errors[error.code] ? errors[error.code] : 'Unable to load watchlist data. Please try again.'
)
export async function watchRequest<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch('/api/watchlists' + path, options)
  const body = await response.json()
  if (!response.ok) throw new WatchError(response.status, body.error || 'request_failed')
  return body as T
}
const statuses: Record<string, translationKeys> = {
  populating: 'Populating tournament data, please wait…',
  not_posted: 'Schedule not posted',
  unavailable: 'Temporarily unavailable',
  stale: 'Showing last successful data',
  ready: 'Up to date',
  not_on_schedule: 'Not on current schedule',
}
export const watchStatus = (state?: string) => t(statuses[state || ''] || 'Temporarily unavailable')

// Source dates and clock times are calendar values, never parsed as UTC instants.
export function localDate() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}
