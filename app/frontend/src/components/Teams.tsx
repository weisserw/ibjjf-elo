import { useState, useEffect, useCallback, useMemo, type FormEvent } from 'react'
import axios from 'axios'
import Autosuggest from 'react-autosuggest'
import debounce from 'lodash/debounce'
import { useLocalStorage } from '@uidotdev/usehooks'
import { axiosErrorToast } from '../utils'
import { t } from '../translate'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import { isGi } from './BracketUtils'
import './Teams.css'

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
  min_competing_athletes_required?: number
  error?: string
}

type TeamSearchSuggestion = {
  name: string
  slug: string
}

function Teams() {
  const navigate = useNavigate()
  const { setFilters, setOpenFilters, setActiveTab } =
    useAppContext()
  const [searchValue, setSearchValue] = useState('')
  const [searchSuggestions, setSearchSuggestions] = useState<TeamSearchSuggestion[]>([])

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
  const [minCompetingAthletesRequired, setMinCompetingAthletesRequired] =
    useState<number | null>(null)

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

  const debouncedGetSearchSuggestions = useMemo(
    () =>
      debounce(async ({ value }: { value: string }) => {
        if (!value.trim()) {
          setSearchSuggestions([])
          return
        }

        try {
          const response = await axios.get(
            `/api/teams/search?search=${encodeURIComponent(value)}`
          )
          setSearchSuggestions(response.data)
        } catch (err) {
          axiosErrorToast(err)
        }
      }, 300, { trailing: true }),
    []
  )

  const debouncedSetEventNameFetch = useCallback(
    debounce(setEventNameFetch, 750, { trailing: true }),
    []
  )

  useEffect(() => {
    return () => {
      debouncedGetSearchSuggestions.cancel()
    }
  }, [debouncedGetSearchSuggestions])

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
          setMinCompetingAthletesRequired(null)
        } else {
          setTeams(data.teams ?? [])
          setMinCompetingAthletesRequired(
            data.min_competing_athletes_required ?? null
          )
        }
      } catch (err) {
        axiosErrorToast(err)
        setTeams(null)
        setMinCompetingAthletesRequired(null)
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

  const onSearchSuggestionSelected = (suggestion: TeamSearchSuggestion) => {
    navigate(`/team/${encodeURIComponent(suggestion.slug)}`)
  }

  return (
    <div className="container pl-2 pr-2">
      <h2 className="title is-4 mt-6 mb-3">{t('Elite Athlete Lists')}</h2>
      <p className="mb-4">
        {t("Search for a team to view elite athletes who have represented that team.")}
      </p>
      <section className="teams-search-section">
        <div className="control has-icons-left">
          <Autosuggest
            suggestions={searchSuggestions}
            onSuggestionsFetchRequested={debouncedGetSearchSuggestions}
            onSuggestionsClearRequested={() => setSearchSuggestions([])}
            multiSection={false}
            getSuggestionValue={(suggestion) => suggestion.name}
            renderSuggestion={(suggestion) => suggestion.name}
            onSuggestionSelected={(
              _event: FormEvent<HTMLElement>,
              { suggestion }: { suggestion: TeamSearchSuggestion }
            ) => {
              setSearchValue('')
              setSearchSuggestions([])
              onSearchSuggestionSelected(suggestion)
            }}
            inputProps={{
              className: 'input teams-search-input',
              value: searchValue,
              placeholder: t('Find Team'),
              onChange: (
                _event: FormEvent<HTMLElement>,
                { newValue }: { newValue: string }
              ) => setSearchValue(newValue),
            }}
          />
          <span className="icon is-small is-left">
            <i className="fas fa-search" aria-hidden="true"></i>
          </span>
        </div>
      </section>
      <h2 className="title is-4 mt-6 mb-3">{t('Team Event Awards')}</h2>
      <p>
        {t("Search for a past event in our database to view our team rankings based on match outcomes and opponent rating. To encourage competitive participation without pressure, white belts and teens are not included in team rankings.")}
      </p>
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
                  placeholder: t('Search for any past tournament by name'),
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
                  setMinCompetingAthletesRequired(null)
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
            {minCompetingAthletesRequired !== null && (
              <p className="mt-4 mb-1">
                {t('Score is calculated as win ratio multiplied by average defeated rating.')}
                {' '}
                {t('Teams must have at least')} {minCompetingAthletesRequired}{' '}
                {t('competing athletes in this event to qualify.')}
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
    </div>
  )
}

export default Teams
