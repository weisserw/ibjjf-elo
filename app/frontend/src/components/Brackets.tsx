import { useState, useMemo } from 'react'
import axios, { AxiosError } from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom';

import "./Brackets.css"

export interface Event {
  id: string
  name: string
}

interface EventsResponse {
  error?: string
  events?: Event[]
}

export type Gender = 'Male' | 'Female'

export interface Category {
  link: string
  age: string
  belt: string
  weight: string
}

interface CategoriesResponse {
  error?: string
  categories?: Category[]
}

export interface Competitor {
  id: string
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

function Brackets() {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const {
    bracketEvents: events,
    setBracketEvents: setEvents,
    bracketSelectedEvent: selectedEvent,
    setBracketSelectedEvent: setSelectedEvent,
    bracketCategories: categories,
    setBracketCategories: setCategories,
    bracketGender: gender,
    setBracketGender: setGender,
    bracketSelectedCategory: selectedCategory,
    setBracketSelectedCategory: setSelectedCategory,
    bracketCompetitors: competitors,
    setBracketCompetitors: setCompetitors,
    bracketSortColumn: sortColumn,
    setBracketSortColumn: setSortColumn,
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
        setError(data.error)
      } else if (data.events) {
        setEvents(data.events)
        setCategories(null)
        setCompetitors(null)
        setError(null)
        if (data.events.length > 0) {
          setSelectedEvent(data.events[0].id)
        }
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const axiosError = err as AxiosError<any>;
        setError(axiosError.message);
      } else {
        setError(JSON.stringify(err));
      }
    } finally {
      setLoading(false)
    }
  }

  const getCategories = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<CategoriesResponse>('/api/brackets/categories/' + selectedEvent + "/" + gender);
      if (data.error) {
        setError(data.error)
      } else if (data.categories) {
        setCategories(data.categories)
        setCompetitors(null)
        setError(null)
        if (data.categories.length > 0) {
          setSelectedCategory(data.categories[0].link)
        }
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const axiosError = err as AxiosError<any>;
        setError(axiosError.message);
      } else {
        setError(JSON.stringify(err));
      }
    } finally {
      setLoading(false)
    }
  }

  const isGi = (event: Event) => {
    return !/no[ -]gi/.test(event.name.toLowerCase())
  }

  const viewBracket = async () => {
    setLoading(true)
    try {
      const event = events?.find(e => e.id === selectedEvent)
      const category = categories?.find(c => c.link === selectedCategory)
      if (!event || !category) {
        return
      }
      const { data } = await axios.get<CompetitorsResponse>('/api/brackets/competitors', {
        params: {
          link: selectedCategory,
          age: category.age,
          gender,
          gi: isGi(event),
          belt: category.belt,
          weight: category.weight
        }
      });
      if (data.error) {
        setError(data.error)
      } else if (data.competitors) {
        setCompetitors(data.competitors)
        setError(null)
      }
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const axiosError = err as AxiosError<any>;
        setError(axiosError.message);
      } else {
        setError(JSON.stringify(err));
      }
    } finally {
      setLoading(false)
    }
  }

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
    setActiveTab(isGi(event) ? 'Gi' : 'No Gi');
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

  return (
    <section className="section">
      <div className="container">
        <h1 className="title">Live Bracket Lookup</h1>
        <p>
          This tool imports brackets directly from <a href="https://bjjcompsystem.com/" target="_blank" rel="nofollow noreferrer">bjjcompsystem.com</a> and displays the current ratings of the competitors.
        </p>
        <div className="brackets-content">
          <button className="button is-primary" onClick={getEvents}>Get Available Events</button>
          {
            events !== null && (
              <div className="bracket-list">
                {
                  events.length > 0 && (
                    <div className="columns no-bottom-margin">
                      <div className="column no-padding">
                        <select className="select" onChange={e => { setSelectedEvent(e.target.value); setCategories(null); setCompetitors(null) }}>
                          {
                            events.map(event => (
                              <option key={event.id} value={event.id} selected={selectedEvent === event.id}>{event.name}</option>
                            ))
                          }
                        </select>
                      </div>
                      <div className="column no-padding">
                        <select className="select" onChange={e => {setGender(e.target.value as Gender); setCategories(null); setCompetitors(null) }}>
                          <option value="Male" selected={gender === 'Male'}>Male</option>
                          <option value="Female" selected={gender === 'Female'}>Female</option>
                        </select>
                      </div>
                    </div>
                  )
                }
                {
                  events.length > 0 && (
                    <button className="button is-primary" onClick={getCategories}>Get Bracket List</button>
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
            categories !== null && (
              <div className="category-list">
                {
                  categories.length > 0 && (
                    <select className="select" onChange={e => {setSelectedCategory(e.target.value); setCompetitors(null) }}>
                      {
                        categories.map(category => (
                          <option key={category.link} value={category.link} selected={selectedCategory === category.link}>{category.age} {category.belt} {category.weight}</option>
                        ))
                      }
                    </select>
                  )
                }
                {
                  categories.length > 0 && (
                    <button className="button is-primary" onClick={viewBracket}>View Bracket</button>
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
            competitors !== null && (
              // show table
              <table className="table is-fullwidth bracket-table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Team</th>
                    <th className="has-text-right">
                      {
                        sortColumn !== 'seed' ?
                          <a href="#" onClick={columnClicked.bind(null, 'seed')}>Seed</a> :
                          <span>Seed</span>
                      }
                    </th>
                    <th className="has-text-right">
                      {
                        sortColumn !== 'rating' ?
                          <a href="#" onClick={columnClicked.bind(null, 'rating')}>Rating</a> :
                          <span>Rating</span>
                      }
                    </th>
                    <th className="has-text-right">Rank</th>
                  </tr>
                </thead>
                <tbody>
                  {
                    sortedCompetitors?.map(competitor => (
                      <tr key={competitor.id}>
                        {
                          competitor.rank === null ?
                            <td>{competitor.name}</td> :
                            <td><a href="#" onClick={e => athleteClicked(e, competitor.name)}>{competitor.name}</a></td>
                        }
                        <td>{competitor.team}</td>
                        <td className="has-text-right">{competitor.seed}</td>
                        <td className="has-text-right">{competitor.rating ?? ''}</td>
                        <td className="has-text-right">{competitor.rank ?? ''}</td>
                      </tr>
                    ))
                  }
                </tbody>
              </table>
            )
          }
        </div>
      </div>
      {
        error && <div className="notification is-danger">{error}</div>
      }
      {
       loading && <div className="bracket-loader loader"></div> 
      }
    </section>
  );
}
  
export default Brackets
