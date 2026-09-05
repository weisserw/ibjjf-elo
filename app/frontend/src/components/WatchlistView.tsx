import { useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useAppContext } from '../AppContext'
import { t, translateMulti } from '../translate'
import { errorText, localDate, WatchData, WatchError, watchRequest, watchStatus } from './WatchlistShared'
import { WatchName, WatchRating, watchOpponentName, watchTime, watchDay, watchDayGroups, watchCountdown, watchMatchUrgency } from './WatchlistParts'
import './Watchlists.css'

const REFRESH_INTERVAL_MS = 3 * 60 * 1000

export default function WatchlistView() {
  const { id } = useParams()
  const { setBracketSelectedEvent, setBracketSelectedCategory, setBracketCategories,
    setBracketCompetitors, setBracketMatches, setBracketMatLinks } = useAppContext()
  const [data, setData] = useState<WatchData | null>(null)
  const [error, setError] = useState('')
  const [unavailable, setUnavailable] = useState(false)
  const [refreshing, setRefreshing] = useState(false)
  const [nextRefreshAt, setNextRefreshAt] = useState(0)
  const [now, setNow] = useState(Date.now())
  const [retry, setRetry] = useState(0)
  const groups = useMemo(() => watchDayGroups(data?.rows || []), [data])
  const initializing = Boolean(data && data.tournaments.every(tournament => !tournament.fetched_at))
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  useEffect(() => { setData(null); setError(''); setUnavailable(false) }, [id])
  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined
    let controller: AbortController | null = null
    let nextAt = 0
    let ended = false
    const poll = async () => {
      if (stopped || ended || document.hidden || controller) return
      controller = new AbortController()
      setRefreshing(true)
      try {
        const response = await watchRequest<WatchData>(`/${encodeURIComponent(id || '')}/data?local_date=${localDate()}`, { signal: controller.signal })
        if (stopped) return
        setData(response); setError('')
      } catch (e) {
        if (stopped) return
        if (e instanceof WatchError && (e.status === 404 || e.status === 410)) {
          ended = true; setUnavailable(true); setData(null)
        }
        setError(errorText(e))
      } finally {
        controller = null
        if (!stopped) {
          setRefreshing(false)
          nextAt = Date.now() + REFRESH_INTERVAL_MS
          setNow(Date.now()); setNextRefreshAt(nextAt)
          if (!document.hidden && !ended) timer = setTimeout(poll, REFRESH_INTERVAL_MS)
        }
      }
    }
    const visibility = () => {
      clearTimeout(timer)
      if (!document.hidden && !ended) {
        if (Date.now() >= nextAt) void poll()
        else timer = setTimeout(poll, nextAt - Date.now())
      }
    }
    void poll()
    document.addEventListener('visibilitychange', visibility)
    return () => { stopped = true; clearTimeout(timer); controller?.abort(); document.removeEventListener('visibilitychange', visibility) }
  }, [id, retry])

  return <section className="container watchlist watch-view px-3">
    <h1 className="title">{t('Saved Watchlist')}</h1>
    <div className="notification is-info">
      <strong>{t('Bookmark this page to quickly access your watchlist')}</strong>
    </div>
    <div className="watch-actions pb-3">
      <Link className="button" to={`/tournaments/watchlists?edit=${encodeURIComponent(id || '')}`}>{t('Edit this watchlist')}</Link>
    </div>
    <p className="watch-refresh-status" role="timer" aria-live="off">{!unavailable && (refreshing ? t('Refreshing…') : nextRefreshAt ? `${t('Updates in')} ${watchCountdown(nextRefreshAt, now)}...` : '')}</p>
    {error && <div className="notification is-warning" role="alert">{error}
      {data && <p>{t('Showing last successful data')}</p>}
      {!unavailable && <button className="button" onClick={() => setRetry(r => r + 1)}>{t('Try again')}</button>}
    </div>}
    {unavailable && <Link to="/tournaments/watchlists">{t('Create a new watchlist')}</Link>}
    {(!data || initializing) && !error && <p role="status">{t('Populating tournament data, please wait…')}</p>}
    {data && !initializing && <>
      {groups.map(([date, rows]) => <section className="watch-day" key={date || 'unscheduled'}>
      {date && <h2 className="title is-5 mb-3">{watchDay(date)}</h2>}
      <div className="watch-cards">
        {rows.map(row => <article key={row.athlete.id || `name:${row.athlete.selection_name}`} className={`watch-card ${row.state === 'not_on_schedule' ? 'watch-gray' : ''} ${row.match ? watchMatchUrgency(row.match.local_date, row.match.local_time, now) : ''}`}>
          <h3>
            <WatchName name={row.athlete.name} profile_url={row.athlete.profile_url} />
            {row.match && <> <WatchRating side={row.competitor} />{' vs'}{watchOpponentName(row.opponent) === t('TBD') ? ' ' : <br />}
              <WatchName name={watchOpponentName(row.opponent)} profile_url={row.opponent?.profile_url || null} />{' '}
              <WatchRating side={row.opponent} />
            </>}
          </h3>
          {row.match ? <>
            <div className="watch-when"><strong>{watchTime(row.match.local_time)} · {t('Mat')} {row.match.mat}</strong></div>
            <p>{row.match.bracket_category ? <Link to="/tournaments" onClick={() => {
              setBracketCategories(null); setBracketCompetitors(null)
              setBracketMatches(null); setBracketMatLinks(null)
              setBracketSelectedEvent(row.match!.event_id)
              setBracketSelectedCategory(row.match!.bracket_category!)
            }}>{translateMulti(row.match.division)}</Link> : translateMulti(row.match.division)}</p>
          </> : <p>{watchStatus(row.state)}</p>}
          {row.match && <p className="watch-tournament">{data.tournaments.find(e => e.event_id === row.match?.event_id)?.name}</p>}
        </article>)}
      </div>
      </section>)}
    </>}
  </section>
}
