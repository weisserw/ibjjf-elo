import { useState, useMemo, useEffect } from 'react'
import axios, { AxiosError } from 'axios'
import classNames from 'classnames'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable from './BracketTable'

import "./Brackets.css"

export interface Event {
  id: string
  name: string
}

interface EventsResponse {
  error?: string
  events?: Event[]
}

export interface Category {
  link: string
  age: string
  belt: string
  weight: string
  gender: string
}

interface CategoriesResponse {
  error?: string
  categories?: Category[]
}

export interface Competitor {
  ordinal: number
  id: string | null
  ibjjf_id: string | null
  seed: number
  name: string
  team: string
  rating: number | null
  rank: number | null
}

interface CompetitorsResponse {
  error?: string
  competitors?: Competitor[]
}

export type SortColumn = 'rating' | 'seed'

export type Tabs = 'Live' | 'Registrations'

interface RegistrationCategoriesResponse {
  event_name?: string
  categories?: string[]
  error?: string
}

function Brackets() {
  const [error, setError] = useState<string | null>(null)
  const [registrationError, setRegistrationError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const {
    bracketEvents: events,
    setBracketEvents: setEvents,
    bracketSelectedEvent: selectedEvent,
    setBracketSelectedEvent: setSelectedEvent,
    bracketCategories: categories,
    setBracketCategories: setCategories,
    bracketSelectedCategory: selectedCategory,
    setBracketSelectedCategory: setSelectedCategory,
    bracketCompetitors: competitors,
    setBracketCompetitors: setCompetitors,
    bracketSortColumn: sortColumn,
    setBracketSortColumn: setSortColumn,
    bracketActiveTab,
    setBracketActiveTab,
    bracketRegistrationUrl: registrationUrl,
    setBracketRegistrationUrl: setRegistrationUrl,
    bracketRegistrationEventName: registrationEventName,
    setBracketRegistrationEventName: setRegistrationEventName,
    bracketRegistrationEventUrl: registrationEventUrl,
    setBracketRegistrationEventUrl: setRegistrationEventUrl,
    bracketRegistrationCategories: registrationCategories,
    setBracketRegistrationCategories: setRegistrationCategories,
    bracketRegistrationSelectedCategory: selectedRegistrationCategory,
    setBracketRegistrationSelectedCategory: setSelectedRegistrationCategory,
    bracketRegistrationCompetitors: registrationCompetitors,
    setBracketRegistrationCompetitors: setRegistrationCompetitors,
    setFilters,
    setOpenFilters,
    setActiveTab,
  } = useAppContext()

  const navigate = useNavigate()

  const getEvents = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<EventsResponse>('/api/brackets/events');
      if (data.error) {
        setEvents(null)
        setError(data.error)
      } else if (data.events) {
        setEvents(data.events)
        setError(null)

        const event = data.events.find(e => e.id === selectedEvent)
        if (event) {
          setSelectedEvent(event.id)
        } else if (!event && data.events.length > 0) {
          setSelectedEvent(data.events[0].id)
        } else {
          setSelectedEvent(null)
          setCategories(null)
          setCompetitors(null)
        }
      }
    } catch (err) {
      handleError(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    getEvents()
  }, [])

  const categoryString = (category: Category) => {
    return `${category.belt} / ${category.age} / ${category.gender} / ${category.weight}`
  }

  const handleError = (err: any, registration?: boolean) => {
    if (axios.isAxiosError(err)) {
      const axiosError = err as AxiosError<any>;
      if (axiosError.response?.data?.error) {
        if (registration) {
          setRegistrationError(axiosError.response.data.error);
        } else {
          setError(axiosError.response.data.error);
        }
      } else {
        if (registration) {
          setRegistrationError(axiosError.message);
        } else {
          setError(axiosError.message);
        }
      }
    } else {
      if (registration) {
        setRegistrationError(JSON.stringify(err));
      } else {
        setError(JSON.stringify(err));
      }
    }
  }

  const getCategories = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<CategoriesResponse>('/api/brackets/categories/' + selectedEvent);
      if (data.error) {
        setCategories(null)
        setError(data.error)
      } else if (data.categories) {
        setCategories(data.categories)
        setError(null)

        const category = data.categories.find(c => categoryString(c) === selectedCategory)

        if (category) {
          setSelectedCategory(categoryString(category))
        } else {
          let selected: string | null = null
          // select adult / black / heavy by default
          for (const category of data.categories) {
            if (category.age === 'Adult' && category.belt === 'BLACK' && category.weight === 'Heavy') {
              selected = categoryString(category)
              break
            }
          }
          // otherwise use the first adult black category
          if (!selected) {
            for (const category of data.categories) {
              if (category.age === 'Adult' && category.belt === 'BLACK') {
                selected = categoryString(category)
                break
              }
            }
          }
          // finally use the first category
          if (!selected && data.categories.length > 0) {
            selected = categoryString(data.categories[0])
          }

          if (selected) {
            setSelectedCategory(selected)
          } else {
            setSelectedCategory(null)
            setCompetitors(null)
          }
        }
      }
    } catch (err) {
      handleError(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedEvent) {
      getCategories()
    }
  }, [events, selectedEvent])

  const isGi = (name: string) => {
    return !/no[ -]gi/.test(name.toLowerCase())
  }

  const viewBracket = async () => {
    setLoading(true)
    try {
      const event = events?.find(e => e.id === selectedEvent)
      const category = categories?.find(c => categoryString(c) === selectedCategory)
      if (!event || !category) {
        return
      }
      const { data } = await axios.get<CompetitorsResponse>('/api/brackets/competitors', {
        params: {
          link: category.link,
          age: category.age,
          gender: category.gender,
          gi: isGi(event.name),
          belt: category.belt,
          weight: category.weight
        }
      });
      if (data.error) {
        setCompetitors(null)
        setError(data.error)
      } else if (data.competitors) {
        setCompetitors(data.competitors)
        setError(null)
      }
    } catch (err) {
      handleError(err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedCategory) {
      viewBracket()
    }
  }, [categories, selectedCategory])

  const getRegistrationCompetitors = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<CompetitorsResponse>('/api/brackets/registrations/competitors', {
        params: {
          link: registrationEventUrl,
          division: selectedRegistrationCategory,
          gi: isGi(registrationEventName)
        }
      });
      if (data.error) {
        setRegistrationCompetitors(null)
        setRegistrationError(data.error)
      } else if (data.competitors) {
        setRegistrationCompetitors(data.competitors)
        setRegistrationError(null)
      }
    } catch (err) {
      handleError(err, true)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (registrationEventUrl && selectedRegistrationCategory) {
      getRegistrationCompetitors()
    }
  }, [registrationEventUrl, selectedRegistrationCategory])

  const athleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()
    const event = events?.find(e => e.id === selectedEvent);
    if (!event) {
      return;
    }
    setFilters({
      athlete_name: name,
    });
    setOpenFilters({athlete: true, event: false, division: false});
    setActiveTab(isGi(event.name) ? 'Gi' : 'No Gi');
    navigate('/database');
  }

  const registrationAthleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()
    setFilters({
      athlete_name: name,
    });
    setOpenFilters({athlete: true, event: false, division: false});
    setActiveTab(isGi(registrationEventName) ? 'Gi' : 'No Gi');
    navigate('/database');
  }

  const columnClicked = (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => {
    ev.preventDefault()
    setSortColumn(column)
  }

  const sortedCompetitors = useMemo(() => {
    if (competitors === null) {
      return null
    }
    return [...competitors].sort((a, b) => {
      if (sortColumn === 'rating') {
        const aRating = a.rating ?? -1;
        const bRating = b.rating ?? -1;
        if (aRating === bRating) {
          return a.seed - b.seed
        } else {
          return bRating - aRating
        }
      } else {
        return a.seed - b.seed
      }
    })
  }, [competitors, sortColumn])

  const sortedRegistrationCompetitors = useMemo(() => {
    if (registrationCompetitors === null) {
      return null
    }
    return [...registrationCompetitors].sort((a, b) => {
      const aRating = a.rating ?? -1;
      const bRating = b.rating ?? -1;
      if (aRating === bRating) {
        return a.name.localeCompare(b.name)
      } else {
        return bRating - aRating
      }
    });
  }, [registrationCompetitors])

  const onRegistrationUrlKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'Enter' && registrationUrl) {
      getRegistrationCategories()
    }
  }

  const getRegistrationCategories = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<RegistrationCategoriesResponse>('/api/brackets/registrations/categories', {
        params: {
          link: registrationUrl
        }
      });
      if (data.error) {
        setRegistrationCategories(null)
        setRegistrationEventName('')
        setRegistrationEventUrl('')
        setRegistrationError(data.error)
      } else if (data.categories && data.event_name) {
        setRegistrationError(null)
        setRegistrationEventName(data.event_name)
        setRegistrationEventUrl(registrationUrl)
        setRegistrationCategories(data.categories)

        let selected: string | null | undefined = null

        selected = data.categories.find(c => c.includes('BLACK / Adult / Male / Heavy'))

        // otherwise use the first adult black category
        if (!selected) {
          selected = data.categories.find(c => c.includes('BLACK / Adult / Male'))
        }
        // finally use the first category
        if (!selected && data.categories.length > 0) {
          selected = data.categories[0]
        }

        if (selected) {
          setSelectedRegistrationCategory(selected)
        } else {
          setSelectedRegistrationCategory(null)
          setRegistrationCompetitors(null)
        }
      }
    } catch (err) {
      handleError(err, true)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="section">
      <div className="container">
        <div className="tabs">
          <ul>
            <li onClick={() => setBracketActiveTab('Live')} className={classNames({"is-active": bracketActiveTab === 'Live'})}><a>Live Brackets</a></li>
            <li onClick={() => setBracketActiveTab('Registrations')} className={classNames({"is-active": bracketActiveTab === 'Registrations'})}><a>Registrations</a></li>
          </ul>
        </div>
        {
          bracketActiveTab === 'Live' && (
            <p>
              This tool imports brackets from <a href="https://bjjcompsystem.com/" target="_blank" rel="nofollow noreferrer">bjjcompsystem.com</a> and displays the current ratings of the competitors.
              Brackets are typically posted 1-2 days before an event starts.
            </p>
          )
        }
        {
          bracketActiveTab === 'Registrations' && (
            <p>
              This tool imports registrations from the IBJJF registration system and displays the current ratings of the competitors. To import a registration URL,
              find an event on <a href="https://ibjjf.com/" target="_blank" rel="nofollow noreferrer">ibjjf.com</a>, select "ATHLETES LIST BY DIVISIONS" from the event page,
              then copy and paste the URL from the browser address bar into the box below:
            </p>
          )
        }
        <div className="brackets-content">
          {
            bracketActiveTab === 'Live' && (
            <div>
              {
                events !== null && (
                  <div className="bracket-list">
                    {
                      events.length > 0 && (
                        <div className="columns no-bottom-margin">
                          <div className="column no-padding">
                            <div className="field">
                              <div className="select">
                                <select value={selectedEvent ?? ''} onChange={e => { setSelectedEvent(e.target.value); }}>
                                  {
                                    events.map(event => (
                                      <option key={event.id} value={event.id}>{event.name}</option>
                                    ))
                                  }
                                </select>
                              </div>
                            </div>
                          </div>
                        </div>
                      )
                    }
                    {
                      events.length === 0 && (
                        <div className="notification is-warning">No events found</div>
                      )
                    }
                  </div>
                )
              }
              {
                (events !== null && categories !== null) && (
                  <div className="category-list">
                    {
                      categories.length > 0 && (
                        <div className="field">
                          <div className="select">
                            <select className="select" value={selectedCategory ?? ''} onChange={e => {setSelectedCategory(e.target.value); }}>
                              {
                                categories.map(category => (
                                  <option key={category.link} value={categoryString(category)}>{categoryString(category)}</option>
                                ))
                              }
                            </select>
                          </div>
                        </div>
                      )
                    }
                    {
                      categories.length === 0 && (
                        <div className="notification is-warning">No valid brackets found</div>
                      )
                    }
                  </div>
                )
              }
              {
                error && <div className="notification is-danger mt-4">{error}</div>
              }
              {
                (events !== null && categories !== null && competitors !== null) && (
                  <BracketTable competitors={sortedCompetitors}
                                sortColumn={sortColumn}
                                showSeed={true}
                                columnClicked={columnClicked}
                                athleteClicked={athleteClicked} />
                )
              }
              {
                loading && <div className="bracket-loader loader mt-4"></div>
              }
            </div>
            )
          }
          {
            bracketActiveTab === 'Registrations' && (
              <div>
                <div className="registrations">
                  <div className="field">
                    <div className="control">
                      <input className="input" type="text" placeholder="Paste registration URL e.g. https://www.ibjjfdb.com/ChampionshipResults/NNNN/PublicRegistrations" value={registrationUrl} onKeyDown={onRegistrationUrlKeyDown} onChange={e => setRegistrationUrl(e.target.value)} />
                    </div>
                  </div>
                  <div className="registrations-get">
                    <button className="button is-info" onClick={getRegistrationCategories} disabled={!registrationUrl}>Get Categories</button>
                  </div>
                </div>
                {
                  registrationError && <div className="notification is-danger mt-4">{registrationError}</div>
                }
                {
                (registrationEventUrl !== null && registrationCategories !== null) && (
                  <div className="category-list">
                    <p><strong>{registrationEventName}</strong></p>
                    {
                      registrationCategories.length > 0 && (
                        <div className="field">
                          <div className="select">
                            <select className="select" value={selectedRegistrationCategory ?? ''} onChange={e => {setSelectedRegistrationCategory(e.target.value); }}>
                              {
                                registrationCategories.map(category => (
                                  <option key={category} value={category}>{category}</option>
                                ))
                              }
                            </select>
                          </div>
                        </div>
                      )
                    }
                    {
                      registrationCategories.length === 0 && (
                        <div className="notification is-warning">No valid brackets found</div>
                      )
                    }
                  </div>)
                }
                {
                  (registrationEventUrl !== null && registrationCategories !== null && registrationCompetitors !== null) && (
                    <BracketTable competitors={sortedRegistrationCompetitors}
                                  showSeed={false}
                                  athleteClicked={registrationAthleteClicked} />
                  )
                }
                {
                  loading && <div className="bracket-loader loader mt-4"></div>
                }
              </div>
            )
          }
        </div>
        <div className="notification mt-5">
          We cache responses from the IBJJF servers. If you don't see the latest data, try again in a few minutes.
        </div>
      </div>

    </section>
  );
}
  
export default Brackets
