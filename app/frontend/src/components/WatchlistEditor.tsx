import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { t } from '../translate'
import { errorText, WatchAthlete, WatchSelection, WatchTournament, watchRequest } from './WatchlistShared'
import './Watchlists.css'

interface SearchResults {
  athletes: WatchAthlete[]
  teams: string[]
  next_cursor: string | null
  eligible_selected_ids: string[]
  registration_ready: boolean
}

export default function WatchlistEditor() {
  const [params] = useSearchParams()
  const edit = params.get('edit')
  const [tournaments, setTournaments] = useState<WatchTournament[]>([])
  const [eventIds, setEventIds] = useState<string[]>([])
  const [selected, setSelected] = useState<WatchAthlete[]>([])
  const [validIds, setValidIds] = useState<string[]>([])
  const [query, setQuery] = useState('')
  const [teams, setTeams] = useState<string[]>([])
  const [addingTeam, setAddingTeam] = useState(false)
  const teamRequest = useRef<AbortController | null>(null)
  const [results, setResults] = useState<WatchAthlete[]>([])
  const [cursor, setCursor] = useState<string | null>(null)
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [initializing, setInitializing] = useState(true)
  const [ready, setReady] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [searchError, setSearchError] = useState('')
  const [retry, setRetry] = useState(0)
  const [loadRetry, setLoadRetry] = useState(0)
  const [initialFailed, setInitialFailed] = useState(false)
  const eventKey = [...eventIds].sort().join(',')
  const selectedKey = selected.map(a => a.id).sort().join(',')

  useEffect(() => () => teamRequest.current?.abort(), [edit])

  useEffect(() => {
    const controller = new AbortController()
    setInitializing(true)
    setInitialFailed(false)
    setError('')
    Promise.all([
      watchRequest<{ tournaments: WatchTournament[] }>('/tournaments', { signal: controller.signal }),
      edit ? watchRequest<WatchSelection>('/' + encodeURIComponent(edit), { signal: controller.signal }) : Promise.resolve(null),
    ]).then(([available, saved]) => {
      if (controller.signal.aborted) return
      setTournaments(available.tournaments)
      if (saved) {
        setEventIds(saved.selection.event_ids)
        setSelected(saved.athletes)
        setTournaments([...available.tournaments, ...saved.tournaments.filter(e => !available.tournaments.some(a => a.event_id === e.event_id)).map(e => ({ ...e, selectable: false }))])
      }
    }).catch(e => { if (!controller.signal.aborted) { setError(errorText(e)); setInitialFailed(true) } })
      .finally(() => { if (!controller.signal.aborted) setInitializing(false) })
    return () => controller.abort()
  }, [edit, loadRetry])

  useEffect(() => {
    const controller = new AbortController()
    let timer: ReturnType<typeof setTimeout>
    if (!eventKey) {
      setResults([]); setTeams([]); setValidIds([]); setLoading(false); setNextCursor(null)
      return
    }
    if (!query.trim()) { setResults([]); setTeams([]); setNextCursor(null) }
    setLoading(true)
    setSearchError('')
    const run = async () => {
      const search = new URLSearchParams({ q: query })
      eventKey.split(',').forEach(id => search.append('event_id', id))
      selectedKey.split(',').filter(Boolean).forEach(id => search.append('selected_id', id))
      if (cursor) search.set('cursor', cursor)
      try {
        const response = await watchRequest<SearchResults>('/athletes?' + search, { signal: controller.signal })
        if (controller.signal.aborted) return
        setResults(previous => cursor ? [...new Map([...previous, ...response.athletes].map(a => [a.id, a])).values()] : response.athletes)
        setNextCursor(response.next_cursor)
        setTeams(response.teams || [])
        setValidIds(response.eligible_selected_ids)
        setReady(response.registration_ready)
        if (!response.registration_ready) timer = setTimeout(run, 5000)
      } catch (e) {
        if (!controller.signal.aborted) { setSearchError(errorText(e)); setValidIds([]) }
      } finally {
        if (!controller.signal.aborted) setLoading(false)
      }
    }
    timer = setTimeout(run, 350)
    return () => { controller.abort(); clearTimeout(timer) }
  }, [eventKey, selectedKey, query, cursor, retry])

  const invalid = selected.filter(a => !validIds.includes(a.id))
  const selectedEvents = tournaments.filter(e => eventIds.includes(e.event_id))

  async function addTeam(team: string) {
    const controller = new AbortController()
    teamRequest.current = controller
    setAddingTeam(true); setError('')
    const additions = new Map(selected.map(a => [a.id, a]))
    let page: string | null = null
    try {
      do {
        const search = new URLSearchParams({ q: team, mode: 'team_exact' })
        eventIds.forEach(id => search.append('event_id', id))
        if (page) search.set('cursor', page)
        const response = await watchRequest<SearchResults>('/athletes?' + search, { signal: controller.signal })
        if (controller.signal.aborted) return
        for (const athlete of response.athletes) {
          if (athlete.trackable && additions.size < 200) additions.set(athlete.id, athlete)
        }
        page = response.next_cursor
      } while (page && additions.size < 200)
      setSelected([...additions.values()]); setCursor(null)
    } catch (e) {
      if (!controller.signal.aborted) setError(errorText(e))
    } finally {
      if (!controller.signal.aborted) setAddingTeam(false)
    }
  }

  async function save() {
    setSaving(true); setError('')
    try {
      const response = await watchRequest<{ url: string }>('', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: eventIds, athlete_ids: selected.map(a => a.id) }),
      })
      const url = new URL(response.url, window.location.origin).href
      window.location.assign(url)
    } catch (e) {
      setError(errorText(e))
    } finally { setSaving(false) }
  }

  return <section className="watchlist watch-editor">
    <p className="mb-4">{t('Choose tournaments, then select athletes to follow their next matches.')}</p>
    {initializing && <p role="status">{t('Loading…')}</p>}
    {error && <div className="notification is-warning" role="alert">{error} <button className="button" onClick={() => initialFailed ? setLoadRetry(r => r + 1) : setRetry(r => r + 1)}>{t('Try again')}</button></div>}
    <fieldset disabled={initializing || saving || addingTeam}>
      <legend className="label mt-4">{t('Tournaments')}</legend>
      <div className="watch-picker">
        {tournaments.map(event => <label className="watch-choice" key={event.event_id}>
          <input type="checkbox" checked={eventIds.includes(event.event_id)}
            disabled={!eventIds.includes(event.event_id) && (!event.selectable || eventIds.length >= 10)}
            onChange={() => { setEventIds(ids => ids.includes(event.event_id) ? ids.filter(id => id !== event.event_id) : [...ids, event.event_id]); setCursor(null); setValidIds([]) }} />
          <span>{event.name}<small>{event.start_date} – {event.end_date}</small>
            {!event.selectable && <small>{t('Tournament unavailable or dates missing')}</small>}
          </span>
        </label>)}
      </div>
      {!initializing && !tournaments.length && <p>{t('No upcoming tournaments are available.')}</p>}
      {selectedEvents.some(event => event.is_kids_tournament) && (
        <div className="notification is-warning mt-4">{t("Note: we do not load age divisions younger than Teen 1.")}</div>
      )}
      <div className="field mt-4">
        <label className="label" htmlFor="watch-search">{t('Find athletes or teams')}</label>
        <div className="watch-search-controls">
          <input id="watch-search" className="input" type="search" value={query} disabled={!eventIds.length}
            placeholder={t('Search selected tournament registrations')}
            onChange={e => { setQuery(e.target.value); setCursor(null) }} />
        </div>
      </div>
      <p role="status" aria-live="polite">{loading ? t('Loading…') : searchError || (!ready && eventIds.length ? t('Registration data is not ready. Importing, please wait…') : '')}</p>
      {!!searchError && <button className="button" onClick={() => setRetry(r => r + 1)}>{t('Try again')}</button>}
      {!!query.trim() && !loading && !searchError && ready && !!eventIds.length && !results.length && !teams.length && <p>{t('No matching athletes in these registrations.')}</p>}
      <div className="watch-results" aria-busy={loading}>
        {(query.trim() ? teams : []).map(team => <div className="watch-result" key={team}>
          <div><strong>{team}</strong><small>{t('Team')}</small></div>
          <button className={`button ${addingTeam ? 'is-loading' : ''}`} disabled={loading || addingTeam || selected.length >= 200}
            onClick={() => void addTeam(team)}>{t('ADD ALL')}</button>
        </div>)}
        {(query.trim() ? results : []).map(athlete => <div className="watch-result" key={athlete.id}>
          <div><strong>{athlete.name}</strong>
            {athlete.registrations?.map((r, i) => <small key={i}>{r.team} · {r.tournament}</small>)}
            {!athlete.trackable && <small>{t('Live tracking is unavailable without an IBJJF athlete ID.')}</small>}
          </div>
          <button className="button" disabled={loading || !athlete.trackable || selected.some(a => a.id === athlete.id) || selected.length >= 200}
            onClick={() => { setSelected(a => [...a, athlete]); setCursor(null) }}>{selected.some(a => a.id === athlete.id) ? t('Added') : t('Add')}</button>
        </div>)}
      </div>
      {!!query.trim() && nextCursor && <button className="button mt-2" disabled={loading} onClick={() => setCursor(nextCursor)}>{t('Load more')}</button>}
      <h2 className="label mt-4">{t('Selected athletes')}</h2>
      <div className="watch-selected">
        {!selected.length && <p>{t('None')}</p>}
        {selected.map(athlete => <div className="watch-result" key={athlete.id}>
          <span>{athlete.name || t('Athlete unavailable')}
            {!loading && !searchError && !validIds.includes(athlete.id) && <small>{t('No longer eligible for the selected tournaments')}</small>}
          </span>
          <button className="button" aria-label={`${t('Remove')} ${athlete.name}`} onClick={() => { setSelected(a => a.filter(s => s.id !== athlete.id)); setCursor(null) }}>{t('Remove')}</button>
        </div>)}
      </div>
    </fieldset>
    <div className="watch-save">
      <button className={`button is-primary is-fullwidth ${saving ? 'is-loading' : ''}`}
        disabled={saving || addingTeam || initializing || loading || !!searchError || !eventIds.length || !selected.length || !!invalid.length || selectedEvents.some(e => !e.selectable)}
        onClick={save}>{t('Open watchlist')}</button>
    </div>
  </section>
}
