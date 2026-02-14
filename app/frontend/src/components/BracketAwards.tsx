import { useState, useEffect, useCallback } from 'react'
import axios from 'axios'
import Autosuggest from 'react-autosuggest'
import debounce from 'lodash/debounce'
import { useLocalStorage } from '@uidotdev/usehooks'
import { axiosErrorToast } from '../utils'
import { t } from '../translate'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import { isGi } from './BracketUtils'

interface TeamAward {
  place: number
  team_name: string
  wins: number
  win_ratio: number
  avg_defeated_rating: number | null
  adjusted_ratio: number
}

interface TeamAwardsResponse {
  teams?: TeamAward[]
  min_wins_required?: number
  error?: string
}

function BracketAwards() {
  const navigate = useNavigate()
  const { filters, setFilters, openFilters, setOpenFilters, setActiveTab } =
    useAppContext()

  const [eventName, setEventName] = useLocalStorage<string>(
    'bracketAwardsEventName',
    ''
  )
  const [eventNameFetch, setEventNameFetch] = useLocalStorage<string>(
    'bracketAwardsEventNameFetch',
    ''
  )
  const [eventSuggestions, setEventSuggestions] = useState<string[]>([])
  const [recentEvents, setRecentEvents] = useState<string[]>([])
  const [recentEventSelection, setRecentEventSelection] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [teams, setTeams] = useState<TeamAward[] | null>(null)
  const [minWinsRequired, setMinWinsRequired] = useState<number | null>(null)

  const getEventSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(
        `/api/events?search=${encodeURIComponent(value)}&historical=false`
      )
      setEventSuggestions(response.data)
    } catch (err) {
      axiosErrorToast(err)
    }
  }

  const debouncedGetEventSuggestions = useCallback(
    debounce(getEventSuggestions, 300, { trailing: true }),
    []
  )

  const debouncedSetEventNameFetch = useCallback(
    debounce(setEventNameFetch, 750, { trailing: true }),
    []
  )

  useEffect(() => {
    const getRecentEvents = async () => {
      try {
        const response = await axios.get<string[]>('/api/awards/events/recent', {
          params: { limit: 10 },
        })
        setRecentEvents(response.data)
      } catch (err) {
        axiosErrorToast(err)
      }
    }

    getRecentEvents()
  }, [])

  useEffect(() => {
    if (!eventNameFetch) {
      return
    }

    const getAwards = async () => {
      setLoading(true)
      setError(null)
      try {
        const { data } = await axios.get<TeamAwardsResponse>(
          '/api/awards/teams',
          {
            params: {
              event_name: eventNameFetch,
            },
          }
        )
        if (data.error) {
          setError(data.error)
          setTeams(null)
          setMinWinsRequired(null)
        } else {
          setTeams(data.teams ?? [])
          setMinWinsRequired(data.min_wins_required ?? null)
        }
      } catch (err) {
        axiosErrorToast(err)
        setTeams(null)
        setMinWinsRequired(null)
      } finally {
        setLoading(false)
      }
    }

    getAwards()
  }, [eventNameFetch])

  const placeDisplay = (place: number) => {
    if (place === 1) {
      return '🥇'
    }
    if (place === 2) {
      return '🥈'
    }
    if (place === 3) {
      return '🥉'
    }
    return place.toString()
  }

  const asExactFilter = (value: string) => {
    const trimmed = value.trim()
    if (trimmed.startsWith('"') && trimmed.endsWith('"')) {
      return trimmed
    }
    return `"${trimmed}"`
  }

  const teamClicked = (ev: React.MouseEvent<HTMLAnchorElement>, teamName: string) => {
    ev.preventDefault()

    const newFilters = {
      event_name: asExactFilter(eventNameFetch),
      team_name: asExactFilter(teamName),
    }
    setFilters(newFilters)
    setOpenFilters({ division: false, athlete: true, event: true })
    setActiveTab(isGi(eventNameFetch) ? 'Gi' : 'No Gi')
    navigate('/database')
  }

  return (
    <div className="brackets-content">
      <div className="bracket-list">
        <div className="field bracket-event-name">
          <label className="label mb-1">{t('Recent tournaments')}:</label>
          <div className="control is-expanded">
            <div className="select is-fullwidth">
              <select
                className="is-fullwidth"
                disabled={!recentEvents.length}
                value={recentEventSelection}
                onChange={(e) => {
                  const selected = e.target.value
                  setRecentEventSelection(selected)
                  if (!selected) {
                    return
                  }
                  setEventName(selected)
                  setEventNameFetch(selected)
                  setTeams(null)
                  setError(null)
                  setRecentEventSelection('')
                }}
              >
                <option value="">{t('Choose a tournament')}</option>
                {recentEvents.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>
        <div className="field position-relative">
          <div className="control is-expanded bracket-event-name">
            <Autosuggest
              suggestions={eventSuggestions}
              onSuggestionsFetchRequested={debouncedGetEventSuggestions}
              onSuggestionsClearRequested={() => setEventSuggestions([])}
              multiSection={false}
              getSuggestionValue={(suggestion) => suggestion}
              renderSuggestion={(suggestion) => suggestion}
              inputProps={{
                className: 'input',
                value: eventName,
                placeholder: t('Search by Tournament Name'),
                onChange: (_: any, { newValue }) => {
                  setEventName(newValue)
                  debouncedSetEventNameFetch(newValue)
                  setTeams(null)
                },
              }}
            />
          </div>
          {eventName && (
            <span
              className="icon is-small clear-filter"
              onClick={() => {
                setEventName('')
                setEventNameFetch('')
                setTeams(null)
                setMinWinsRequired(null)
                setError(null)
              }}
            >
              <i className="fas fa-times"></i>
            </span>
          )}
        </div>
      </div>
      {loading && <div className="bracket-loader loader mt-4"></div>}
      {error && <div className="notification is-danger mt-4">{error}</div>}
      {!!eventNameFetch && teams !== null && teams.length > 0 && (
        <div className="table-container">
          {minWinsRequired !== null && (
            <p className="mt-4 mb-1">
              Score is calculated as win ratio multiplied by average defeated rating.
              Teams must have at least {minWinsRequired} wins in this event to appear.
            </p>
          )}
          <table className="table is-fullwidth bracket-table">
            <thead>
              <tr>
                <th className="has-text-centered">{t('Place')}</th>
                <th>{t('Team')}</th>
                <th className="has-text-right">{t('Wins')}</th>
                <th className="has-text-right">{t('Win Ratio')}</th>
                <th className="has-text-right">{t('Average Defeated Rating')}</th>
                <th className="has-text-right">{t('Score')}</th>
              </tr>
            </thead>
            <tbody>
              {teams.map((team) => (
                <tr key={`${team.place}-${team.team_name}`}>
                  <td className="has-text-centered">{placeDisplay(team.place)}</td>
                  <td>
                    <a href="#" onClick={(ev) => teamClicked(ev, team.team_name)}>
                      {team.team_name}
                    </a>
                  </td>
                  <td className="has-text-right">{team.wins}</td>
                  <td className="has-text-right">{team.win_ratio.toFixed(1)}%</td>
                  <td className="has-text-right">
                    {team.avg_defeated_rating !== null
                      ? Math.round(team.avg_defeated_rating).toString()
                      : '-'}
                  </td>
                  <td className="has-text-right">
                    {Math.round(team.adjusted_ratio).toString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default BracketAwards
