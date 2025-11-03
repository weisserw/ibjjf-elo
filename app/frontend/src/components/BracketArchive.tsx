import { useState, useMemo, useEffect, useCallback } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable, { type SortColumn } from './BracketTable'
import BracketTree from './BracketTree'
import Autosuggest from 'react-autosuggest'
import { axiosErrorToast, isHistorical } from '../utils';
import debounce from 'lodash/debounce';
import { isGi, handleError, nearestPowerOfTwo } from './BracketUtils'
import { translateMulti, t } from '../translate'
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

  const getEventSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/events?search=${encodeURIComponent(value)}&historical=false`);
      setEventSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetEventSuggestions = useCallback(debounce(getEventSuggestions, 300, {trailing: true}), []);

  const debouncedSetEventNameFetch = useCallback(debounce(setEventNameFetch, 750, {trailing: true}), []);

  const categoryString = (category: Category) => {
    return `${category.belt} / ${category.age} / ${category.gender} / ${category.weight}`
  }

  const columnClicked = (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => {
    ev.preventDefault()
    setSortColumn(column)
  }

  const athleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, id: string) => {
    ev.preventDefault()

    if (!eventNameFetch) {
      return
    }

    setActiveTab(isGi(eventNameFetch) ? 'Gi' : 'No Gi')
    navigate('/athlete/' + encodeURIComponent(id))
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

  const showRatings = useMemo(() => {
    if (selectedCategory && categories) {
      const category = categories.find(c => categoryString(c) === selectedCategory)
      if (category) {
        return !category.age.startsWith('Teen')
      }
    }
    return true
  }, [selectedCategory, categories])

  const showSeed = !isHistorical(eventName);

  const usableSortColumn = useMemo(() => {
    let column = sortColumn
    if (!showRatings && sortColumn === 'rating') {
      column = 'seed'
    }
    if (!showSeed && sortColumn === 'seed') {
      column = 'rating'
    }
    return column
  }, [sortColumn, showRatings, showSeed])

  const sortedCompetitors = useMemo(() => {
    if (competitors === null) {
      return null
    }
    return [...competitors].sort((a, b) => {
      if (usableSortColumn === 'rating') {
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

  const hasMatchNums = useMemo(() => {
    return matches?.some(match => match.match_num !== null) ?? false
  }, [matches]);

  const expectedMatchCount = useMemo(() => {
    if (hasMatchNums) {
      return Math.max(nearestPowerOfTwo(competitors?.length ?? 1), 
                      nearestPowerOfTwo(Math.max(...(competitors?.map(c => c.seed) ?? [1])))) - 1;
    } else {
      return matches?.length ?? 0;
    }
  }, [matches, competitors, hasMatchNums])

  const calculateEnabled = (match: BracketMatch) => {
    return match.red_name !== null && match.blue_name !== null;
  }

  const belt = selectedCategory ? selectedCategory.split(' / ')[0] : '';

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
                              getSuggestionValue={(suggestion) => suggestion}
                              renderSuggestion={(suggestion) => suggestion}
                              inputProps={{
                              className: "input",
                              value: eventName,
                              placeholder: t("Tournament Name"),
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
                                <option key={categoryString(category)} value={categoryString(category)}>{translateMulti(categoryString(category))}</option>
                              ))
                            }
                          </select>
                        </div>
                      </div>
                    </div>
                    <div className="column is-vcentered">
                    {
                      (showRatings && averageRating !== undefined) && (
                        <span>{`${t("Average rating")}: ${averageRating}`}</span>
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
          categories?.some(c => /Teen/.test(c.age)) && (
            <div className="notification is-warning mt-4">{t("Note: we do not load age divisions younger than Teen 1.")}</div>
          )
        }
        {
          loading && <div className="bracket-loader loader mt-4"></div>
        }
        {
          error && <div className="notification is-danger mt-4">{error}</div>
        }
        {
          (!!eventNameFetch && categories !== null && matches !== null) && (
            <BracketTree matches={matches}
                         matchCount={expectedMatchCount}
                         hasMatchNums={hasMatchNums}
                         showSeed={usableSortColumn === 'seed'}
                         showRefresh={false}
                         showRatings={showRatings}
                         belt={belt}
                         calculateClicked={calculateMatch}
                         calculateEnabled={calculateEnabled}/>
          )
        }
        {
          (!!eventNameFetch && categories !== null && competitors !== null) && (
            <BracketTable competitors={sortedCompetitors}
                          sortColumn={usableSortColumn}
                          showSeed={showSeed}
                          showEndRating={true}
                          showRatings={showRatings}
                          showWeight={selectedCategory?.includes(' / Open') ?? false}
                          selectedCategory={selectedCategory}
                          belt={belt}
                          isGi={isGi(eventNameFetch)}
                          columnClicked={columnClicked}
                          athleteClicked={athleteClicked}
                          calculateEnabled={() => true}/>
          )
        }
      </div>
      {
        !showSeed && (
          <div className="notification is-historical mt-4">
            {t("Match data before December 2024 may be incomplete or inaccurate")}
          </div>
        )
      }
    </div>
  );
}

export default BracketArchive;