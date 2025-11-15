import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import classNames from 'classnames'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable, { type SortColumn } from './BracketTable'
import BracketTree from './BracketTree'
import { isGi, handleError, categoryString } from './BracketUtils'
import { translateMulti, t } from '../translate'
import type { CategoriesResponse, LiveCompetitorsResponse, Match as BracketMatch, Competitor } from './BracketUtils'

export interface Event {
  id: string
  name: string
}

interface EventsResponse {
  error?: string
  events?: Event[]
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
    bracketEventTotal: eventTotal,
    setBracketEventTotal: setEventTotal,
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

  const columnClicked = (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => {
    ev.preventDefault()
    setSortColumn(column)
  }

  const athleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, slug: string) => {
    ev.preventDefault()
    const event = events?.find(e => e.id === selectedEvent);
    if (!event) {
      return;
    }
    
    setActiveTab(isGi(event.name) ? 'Gi' : 'No Gi');
    navigate('/athlete/' + encodeURIComponent(slug));
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
        setEventTotal(null)
        setError(data.error)
      } else if (data.categories) {
        setCategories(data.categories)
        setEventTotal(data.total ?? null)
        setError(null)

        const category = data.categories.find(c => categoryString(c) === selectedCategory)

        if (category) {
          setSelectedCategory(categoryString(category))
        } else {
          let selected: string | null = null
          // select adult / black / male / middle by default
          for (const category of data.categories) {
            if ((category.age === 'Adult' || category.age === 'Adulto') &&
                (category.belt === 'BLACK' || category.belt === 'PRETA') &&
                (category.gender === 'Male') &&
                (category.weight === 'Middle' || category.weight === 'Médio')) {
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
          // otherwise use master 1 black belt
          if (!selected) {
            for (const category of data.categories) {
              if (category.age === 'Master 1' &&
                  (category.belt === 'BLACK' || category.belt === 'PRETA') &&
                  (category.gender === 'Male') &&
                  (category.weight === 'Middle' || category.weight === 'Médio')) {
                selected = categoryString(category)
                break
              }
            }
          }
          if (!selected) {
            for (const category of data.categories) {
              if (category.age === 'Master 1' &&
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

  const showRatings = useMemo(() => {
    if (selectedCategory && categories) {
      const category = categories.find(c => categoryString(c) === selectedCategory)
      if (category) {
        return !category.age.startsWith('Teen')
      }
    }
    return true
  }, [selectedCategory, categories])

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

  const showNext = useMemo(() => (
    competitors?.some(c => c.next_when && c.next_where) ?? false
  ), [competitors]);

  const usableSortColumn = useMemo(() => {
    let column = sortColumn;
    if (!showNext && column === 'next') {
      column = 'rating';
    }
    if (!showRatings && column === 'rating') {
      column = 'seed';
    }
    return column;
  }, [sortColumn, showRatings, showNext]);

  const sortedCompetitors = useMemo(() => {
    if (competitors === null) {
      return null
    }
    return [...competitors].sort((a, b) => {
      const aRating = a.ordinal ?? -1;
      const bRating = b.ordinal ?? -1;
      if (usableSortColumn === 'rating') {
        if (aRating === bRating) {
          return a.seed - b.seed
        } else {
          return aRating - bRating
        }
      } else if (usableSortColumn === 'seed') {
        return a.seed - b.seed
      } else {
        if (!a.next_when && !b.next_when) {
          return 0
        } else if (!a.next_when) {
          return 1
        } else if (!b.next_when) {
          return -1
        } else if (a.next_when === b.next_when) {
          if (a.next_where && b.next_where) {
            if (a.next_where === b.next_where) {
              return aRating - bRating
            } else {
              return a.next_where.localeCompare(b.next_where)
            }
          } else {
            return 0
          }
        } else {
          return a.next_when.localeCompare(b.next_when)
        }
      }
    })
  }, [competitors, usableSortColumn])

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

  const calculateEnabled = (match: BracketMatch) => {
    if (!match.red_id || !match.blue_id) {
      return false
    }

    const red_competitor = competitors?.find(c => c.ibjjf_id === match.red_id)
    const blue_competitor = competitors?.find(c => c.ibjjf_id === match.blue_id)
    if (!red_competitor || !blue_competitor) {
      return false
    }
    return (red_competitor.rating !== null && red_competitor.match_count !== null && red_competitor.match_count > 0 &&
            blue_competitor.rating !== null && blue_competitor.match_count !== null && blue_competitor.match_count > 0)
  }

  const calculateEnabledAthlete = (athlete: Competitor) => {
    return athlete.rating !== null && athlete.match_count !== null && athlete.match_count > 0
  }

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

  const belt = selectedCategory ? selectedCategory.split(' / ')[0] : '';

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
                          <select disabled={loading} value={selectedEvent ?? ''} onChange={e => { setSelectedEvent(e.target.value); }}>
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
                  <div className="notification is-warning">{t("No tournaments found")}</div>
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
                  <div className="category-flex">
                    <div className="category-column">
                      <div className="total">
                        {eventTotal !== null &&
                          <span>Total Competitors: {eventTotal.toLocaleString()}</span>
                        }
                      </div>
                      <div className="field">
                        <div className="select">
                          <select disabled={loading} className="select" value={selectedCategory ?? ''} onChange={e => {setSelectedCategory(e.target.value); }}>
                            {
                              categories.map(category => (
                                <option key={category.link} value={categoryString(category)}>{translateMulti(categoryString(category))}</option>
                              ))
                            }
                          </select>
                        </div>
                      </div>
                      <div className="average">
                      {
                        (showRatings && averageRating !== undefined) && (
                          <span>{`${t("Average rating")}: ${averageRating}`}</span>
                        )
                      }
                      </div>
                    </div>
                  </div>
                )
              }
              {
                categories.length === 0 && (
                  <div className="notification is-warning">{t("No valid brackets found. Note: we do not load age divisions younger than Teen 1.")}</div>
                )
              }
            </div>
          )
        }
        {
          error && <div className="notification is-danger mt-4">{error}</div>
        }
        {
          categories?.some(c => /Teen/.test(c.age)) && (
            <div className="notification is-warning mt-4">{t("Note: we do not load age divisions younger than Teen 1.")}</div>
          )
        }
        {
          loading && <div className="bracket-loader loader mt-4"></div>
        }
        {
          (events !== null && categories !== null && matches !== null) && (
            <BracketTree
              matches={matches}
              matchCount={matches.length}
              hasMatchNums={true}
              showSeed={usableSortColumn === 'seed'}
              showRefresh={true}
              isRefreshing={loading}
              showRatings={showRatings}
              belt={belt}
              calculateClicked={calculateMatch}
              calculateEnabled={calculateEnabled}
              refreshClicked={viewBracket}
            />
          )
        }
        <div className="bracket-live-actions">
          {
            (events !== null && categories !== null && competitors !== null && selectedCategoryLink !== null) &&
            <a
              href={`https://bjjcompsystem.com${selectedCategoryLink}`}
              target="_blank"
              rel="noreferrer"
              className="button is-link is-outlined mt-5"
            >
              {t("View Bracket (external)")}
            </a>
          }
          <button disabled={loading} className={classNames("button is-small", {"is-loading": loading})} onClick={viewBracket}>
            <span className="icon is-small">
              <i className="fas fa-sync"></i>
            </span>
          </button>
        </div>
        {
          (events !== null && categories !== null && competitors !== null) && (
            <BracketTable
              competitors={sortedCompetitors}
              sortColumn={usableSortColumn}
              showSeed={true}
              showEndRating={true}
              showNext={showNext}
              showRatings={showRatings}
              belt={belt}
              showWeight={selectedCategory?.includes(' / Open') ?? false}
              selectedCategory={selectedCategory}
              isGi={isGi(selectedEventName ?? '')}
              columnClicked={columnClicked}
              athleteClicked={athleteClicked}
              calculateEnabled={calculateEnabledAthlete}
            />
          )
        }
      </div>
    </div>
  );
}

export default BracketLive;