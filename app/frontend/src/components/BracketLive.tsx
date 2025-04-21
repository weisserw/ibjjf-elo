import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable, { type SortColumn } from './BracketTable'
import BracketTree from './BracketTree'
import { isGi, handleError, type CompetitorsResponse, type Match as BracketMatch } from './BracketUtils'

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

interface LiveCompetitorsResponse extends CompetitorsResponse {
  matches?: BracketMatch[]
}

function BracketLive() {
  const [error, setError] = useState<string | null>(null)
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
    bracketMatches: matches,
    setBracketMatches: setMatches,
    bracketSortColumn: sortColumn,
    setBracketSortColumn: setSortColumn,
    setFilters,
    setOpenFilters,
    setActiveTab,
    setCalcFirstAthlete,
    setCalcSecondAthlete,
    setCalcGender,
    setCalcAge,
    setCalcBelt,
    setCalcFirstWeight,
    setCalcSecondWeight,
    setCalcCustomInfo,
  } = useAppContext()

  const navigate = useNavigate()

  const categoryString = (category: Category) => {
    return `${category.belt} / ${category.age} / ${category.gender} / ${category.weight}`
  }

  const columnClicked = (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => {
    ev.preventDefault()
    setSortColumn(column)
  }

  const athleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()
    const event = events?.find(e => e.id === selectedEvent);
    if (!event) {
      return;
    }
    setFilters({
      athlete_name: '"' + name + '"',
    });
    setOpenFilters({athlete: true, event: false, division: false});
    setActiveTab(isGi(event.name) ? 'Gi' : 'No Gi');
    navigate('/database');
  }

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
      handleError(err, setError)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    getEvents()
  }, [])

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
          // select adult / black / male / heavy by default
          for (const category of data.categories) {
            if ((category.age === 'Adult' || category.age === 'Adulto') &&
                (category.belt === 'BLACK' || category.belt === 'PRETA') &&
                (category.gender === 'Male') &&
                (category.weight === 'Heavy' || category.weight === 'Pesado')) {
              selected = categoryString(category)
              break
            }
          }
          // otherwise use the first adult black category
          if (!selected) {
            for (const category of data.categories) {
              if ((category.age === 'Adult' || category.age === 'Adulto') &&
                  (category.belt === 'BLACK' || category.belt === 'PRETA')) {
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
      handleError(err, setError)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedEvent) {
      getCategories()
    }
  }, [events, selectedEvent])

  const viewBracket = async () => {
    setLoading(true)
    try {
      const event = events?.find(e => e.id === selectedEvent)
      const category = categories?.find(c => categoryString(c) === selectedCategory)
      if (!event || !category) {
        return
      }
      const { data } = await axios.get<LiveCompetitorsResponse>('/api/brackets/competitors', {
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
        if (data.matches) {
          setMatches(data.matches)
        }
        setError(null)
      }
    } catch (err) {
      handleError(err, setError)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (selectedCategory) {
      viewBracket()
    }
  }, [categories, selectedCategory])

  const selectedCategoryLink = useMemo(() => {
    if (selectedCategory && categories) {
      const category = categories.find(c => categoryString(c) === selectedCategory)
      if (category) {
        return category.link
      }
    }
    return null
  }, [selectedCategory, categories])

  const selectedEventName = useMemo(() => {
    if (events && selectedEvent) {
      const event = events.find(e => e.id === selectedEvent)
      if (event) {
        return event.name
      }
    }
    return null
  }, [events, selectedEvent])

  const sortedCompetitors = useMemo(() => {
    if (competitors === null) {
      return null
    }
    return [...competitors].sort((a, b) => {
      if (sortColumn === 'rating') {
        const aRating = a.ordinal ?? -1;
        const bRating = b.ordinal ?? -1;
        if (aRating === bRating) {
          return a.seed - b.seed
        } else {
          return aRating - bRating
        }
      } else {
        return a.seed - b.seed
      }
    })
  }, [competitors, sortColumn])

  const averageRating = useMemo(() => {
    if (competitors === null || competitors.length === 0) {
      return undefined
    }
    const ratings = competitors.map(c => c.rating).filter(r => r !== undefined && r !== null) as number[]
    if (ratings.length === 0) {
      return undefined
    }
    const sum = ratings.reduce((a, b) => a + b, 0)
    return Math.round(sum / ratings.length)
  }, [competitors])

  const calculateMatch = async (match: BracketMatch) => {
    if (!match.red_name || !match.blue_name || !selectedCategory || !selectedEventName) {
      return
    }
    const [belt, age, gender, weight] = selectedCategory.split(' / ');
    setCalcFirstAthlete(match.red_name);
    setCalcSecondAthlete(match.blue_name);
    setCalcGender(gender);
    setActiveTab(isGi(selectedEventName) ? 'Gi' : 'No Gi');
    if (!/Open/i.test(weight)) {
      setCalcFirstWeight(weight);
      setCalcSecondWeight(weight);
      setCalcAge(age);
      setCalcBelt(belt);
      setCalcCustomInfo(true);
    } else {
      setCalcCustomInfo(false);
    }

    navigate('/calculator');
  }

  return (
    <div className="brackets-content">
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
                  <div className="columns no-bottom-margin">
                    <div className="column column-padding is-vcentered">
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
                    </div>
                    <div className="column is-vcentered">
                    {
                      averageRating !== undefined && (
                        <span>{`Average rating: ${averageRating}`}</span>
                      )
                    }
                    </div>
                  </div>
                )
              }
              {
                categories.length === 0 && (
                  <div className="notification is-warning">No valid brackets found. Note: we do not load kids divisions.</div>
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
                          showWeight={selectedCategory?.includes(' / Open') ?? false}
                          isGi={isGi(selectedEventName ?? '')}
                          columnClicked={columnClicked}
                          athleteClicked={athleteClicked} />
          )
        }
        {
          (events !== null && categories !== null && matches !== null) && (
            <BracketTree matches={matches} calculateClicked={calculateMatch}/>
          )
        }
        {
          (events !== null && categories !== null && competitors !== null && selectedCategoryLink !== null) &&
          <a href={`https://bjjcompsystem.com${selectedCategoryLink}`} target="_blank" rel="noreferrer" className="button is-link is-outlined mt-5">View Bracket (external)</a>
        }
        {
          error && <div className="notification is-danger mt-4">{error}</div>
        }
        {
          loading && <div className="bracket-loader loader mt-4"></div>
        }
      </div>
    </div>
  );
}

export default BracketLive;