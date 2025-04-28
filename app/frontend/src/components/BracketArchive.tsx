import { useState, useMemo, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable, { type SortColumn } from './BracketTable'
import BracketTree from './BracketTree'
import Autosuggest from 'react-autosuggest'
import { axiosErrorToast } from '../utils';
import debounce from 'lodash/debounce';
import { isGi, handleError } from './BracketUtils'
import type { LiveCompetitorsResponse, Match as BracketMatch } from './BracketUtils'

export interface Category {
  age: string
  belt: string
  weight: string
  gender: string
}

interface CategoriesResponse {
  error?: string
  categories?: Category[]
}


function BracketArchive() {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [eventSuggestions, setEventSuggestions] = useState<string[]>([])

  const {
    activeTab,
    bracketArchiveEventName: eventName,
    setBracketArchiveEventName: setEventName,
    bracketArchiveEventNameFetch: eventNameFetch,
    setBracketArchiveEventNameFetch: setEventNameFetch,
    bracketArchiveCategories: categories,
    setBracketArchiveCategories: setCategories,
    bracketArchiveSelectedCategory: selectedCategory,
    setBracketArchiveSelectedCategory: setSelectedCategory,
    bracketArchiveCompetitors: competitors,
    setBracketArchiveCompetitors: setCompetitors,
    bracketArchiveMatches: matches,
    setBracketArchiveMatches: setMatches,
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

  const gi = activeTab === 'Gi' ? true : false

  const getEventSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/events?search=${encodeURIComponent(value)}&gi=${gi}&historical=false`);
      setEventSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetEventSuggestions = useCallback(debounce(getEventSuggestions, 300, {trailing: true}), [gi]);

  const debouncedSetEventNameFetch = useCallback(debounce(setEventNameFetch, 750, {trailing: true}), []);

  const categoryString = (category: Category) => {
    return `${category.belt} / ${category.age} / ${category.gender} / ${category.weight}`
  }

  const columnClicked = (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => {
    ev.preventDefault()
    setSortColumn(column)
  }

  const athleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()
    if (!eventNameFetch) {
      return;
    }
    setFilters({
      athlete_name: '"' + name + '"',
    });
    setOpenFilters({athlete: true, event: false, division: false});
    setActiveTab(isGi(eventNameFetch) ? 'Gi' : 'No Gi');
    navigate('/database');
  }

  const getCategories = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<CategoriesResponse>('/api/brackets/archive/categories', {
        params: {
          event_name: eventNameFetch,
        }
      });

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
    if (eventNameFetch) {
      getCategories()
    }
  }, [eventNameFetch])

  const viewBracket = async () => {
    setLoading(true)
    try {
      const category = categories?.find(c => categoryString(c) === selectedCategory)
      if (!eventNameFetch || !category) {
        return
      }
      const { data } = await axios.get<LiveCompetitorsResponse>('/api/brackets/archive/competitors', {
        params: {
          event_name: eventNameFetch,
          age: category.age,
          gender: category.gender,
          belt: category.belt,
          weight: category.weight,
          gi: isGi(eventNameFetch),
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

  const calculateMatch = async (match: BracketMatch) => {
    if (!match.red_name || !match.blue_name || !selectedCategory || !eventNameFetch) {
      return
    }
    const [belt, age, gender, weight] = selectedCategory.split(' / ');
    setCalcFirstAthlete(match.red_name);
    setCalcSecondAthlete(match.blue_name);
    setCalcGender(gender);
    setActiveTab(isGi(eventNameFetch) ? 'Gi' : 'No Gi');
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

  const showSeed = !eventName.includes('(');

  return (
    <div className="brackets-content">
      <div>
        <div className="bracket-list">
          <div className="field position-relative">
            <div className="control is-expanded bracket-event-name">
              <Autosuggest suggestions={eventSuggestions}
                              onSuggestionsFetchRequested={debouncedGetEventSuggestions}
                              onSuggestionsClearRequested={() => setEventSuggestions([])}
                              multiSection={false}
                              getSuggestionValue={(suggestion) => '"' + suggestion + '"'}
                              renderSuggestion={(suggestion) => suggestion}
                              inputProps={{
                              className: "input",
                              value: eventName,
                              placeholder: "Event Name",
                              onChange: (_: any, { newValue }) => {
                                  setEventName(newValue);
                                  debouncedSetEventNameFetch(newValue);
                                  setCategories(null);
                                  setCompetitors(null);
                                  setMatches(null);
                              }
                              }} />
            </div>
            {
              eventName && (
                <span className="icon is-small clear-filter" onClick={() => {
                  setEventName('')
                  setEventNameFetch('')
                  setCategories(null);
                  setCompetitors(null);
                  setMatches(null);
                }}>
                  <i className="fas fa-times"></i>
                </span>
              )
            }
          </div>
        </div>
        {
          (categories !== null) && (
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
            </div>
          )
        }
        {
          loading && <div className="bracket-loader loader mt-4"></div>
        }
        {
          error && <div className="notification is-danger mt-4">{error}</div>
        }
        {
          (!!eventNameFetch && categories !== null && competitors !== null) && (
            <BracketTable competitors={sortedCompetitors}
                          sortColumn={showSeed ? sortColumn : 'rating'}
                          showSeed={showSeed}
                          showEndRating={true}
                          showWeight={selectedCategory?.includes(' / Open') ?? false}
                          isGi={isGi(eventNameFetch)}
                          columnClicked={columnClicked}
                          athleteClicked={athleteClicked} />
          )
        }
        {
          (!!eventNameFetch && categories !== null && matches !== null) && (
            <BracketTree matches={matches}
                        showSeed={sortColumn === 'seed'}
                        calculateClicked={calculateMatch}
                        calculateEnabled={calculateEnabled}/>
          )
        }
      </div>
      {
        !showSeed && (
          <div className="notification is-historical mt-4">
            Match data before December 2024 may be incomplete or inaccurate
          </div>
        )
      }
    </div>
  );
}

export default BracketArchive;