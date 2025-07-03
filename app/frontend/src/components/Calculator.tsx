import { useState, useCallback, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import GiTabs from "./GiTabs"
import Autosuggest from 'react-autosuggest'
import axios, { AxiosResponse } from 'axios'
import { debounce } from 'lodash'
import { axiosErrorToast, ages, isHistorical, type DBRow as Row, type DBResults as Results } from '../utils'
import { useAppContext } from '../AppContext'
import DBTableRows from './DBTableRows'

import "./Calculator.css"

const belts = [
  'WHITE',
  'BLUE',
  'PURPLE',
  'BROWN',
  'BLACK'
];

export const femaleWeights = [
  'Rooster',
  'Light Feather',
  'Feather',
  'Light',
  'Middle',
  'Medium Heavy',
  'Heavy',
  'Super Heavy'
];

export const maleWeights = femaleWeights.concat([
  'Ultra Heavy'
]);

interface PredictResponse {
  first_expected: number;
  second_expected: number;
  first_win: number;
  second_win: number;
  first_loss: number;
  second_loss: number;
  first_tie: number;
  second_tie: number;
  red_handicap: number;
  blue_handicap: number;
  red_k_factor: number;
  blue_k_factor: number;
}

interface AthleteRating {
  rating: number | null;
  age: string | null;
  weight: string | null;
  belt: string | null;
}

function Calculator() {
  const [athleteSuggestions1, setAthleteSuggestions1] = useState<string[]>([])
  const [athleteSuggestions2, setAthleteSuggestions2] = useState<string[]>([])
  const [firstAthleteToFetch, setFirstAthleteToFetch] = useState<string | null>(null)
  const [secondAthleteToFetch, setSecondAthleteToFetch] = useState<string | null>(null)
  const [firstFetchedAthlete, setFirstFetchedAthlete] = useState<AthleteRating | null>(null)
  const [secondFetchedAthlete, setSecondFetchedAthlete] = useState<AthleteRating | null>(null)
  const [firstRating, setFirstRating] = useState('')
  const [secondRating, setSecondRating] = useState('')
  const [firstRatingToPredict, setFirstRatingToPredict] = useState('')
  const [secondRatingToPredict, setSecondRatingToPredict] = useState('')
  const [firstExpected, setFirstExpected] = useState<number | null>(0.0)
  const [secondExpected, setSecondExpected] = useState<number | null>(0.0)
  const [firstWin, setFirstWin] = useState(0)
  const [firstLoss, setFirstLoss] = useState(0)
  const [firstHandicap, setFirstHandicap] = useState(0)
  const [secondHandicap, setSecondHandicap] = useState(0)
  const [data, setData] = useState<Row[]>([])

  const {
    activeTab,
    setFilters,
    setOpenFilters,
    calcGender,
    setCalcGender,
    calcFirstAthlete,
    setCalcFirstAthlete,
    calcSecondAthlete,
    setCalcSecondAthlete,
    calcAge,
    setCalcAge,
    calcBelt,
    setCalcBelt,
    calcFirstWeight,
    setCalcFirstWeight,
    calcSecondWeight,
    setCalcSecondWeight,
    calcCustomInfo,
    setCalcCustomInfo,
    setBracketActiveTab,
    setBracketArchiveEventName,
    setBracketArchiveEventNameFetch,
    setBracketArchiveSelectedCategory,
  } = useAppContext();

  const navigate = useNavigate();

  const divisionBracketClicked = (row: Row) => {
    setBracketActiveTab('Archive')
    setBracketArchiveEventName('"' + row.event + '"')
    setBracketArchiveEventNameFetch('"' + row.event + '"')
    setBracketArchiveSelectedCategory(`${row.belt} / ${row.age} / ${row.gender} / ${row.weight}`)
    navigate('/brackets')
  }

  const athleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()

    setFilters({
      athlete_name: '"' + name + '"',
    });
    setOpenFilters({athlete: true, event: false, division: false});
    navigate('/database');
  }

  // re-fetch athletes if component reloads
  useEffect(() => {
    if (calcFirstAthlete) {
      setFirstAthleteToFetch(calcFirstAthlete);
    }
    if (calcSecondAthlete) {
      setSecondAthleteToFetch(calcSecondAthlete);
    }
  }, []);
  
  useEffect(() => {
    if (firstAthleteToFetch) {
      axios.get<AthleteRating>(`/api/athletes/ratings?name=${encodeURIComponent(firstAthleteToFetch)}&gi=${activeTab === 'Gi' ? 'true' : 'false'}`)
        .then(response => {
          setFirstFetchedAthlete(response.data);
        })
        .catch(error => {
          axiosErrorToast(error);
        });
    } else {
      setFirstFetchedAthlete(null);
    }
  }, [firstAthleteToFetch, activeTab])

  useEffect(() => {
    if (secondAthleteToFetch) {
      axios.get<AthleteRating>(`/api/athletes/ratings?name=${encodeURIComponent(secondAthleteToFetch)}&gi=${activeTab === 'Gi' ? 'true' : 'false'}`)
        .then(response => {
          setSecondFetchedAthlete(response.data);
        })
        .catch(error => {
          axiosErrorToast(error);
        });
    } else {
      setSecondFetchedAthlete(null);
    }
  }, [secondAthleteToFetch, activeTab])

  useEffect(() => {
    if (firstFetchedAthlete) {
      setFirstRating(firstFetchedAthlete.rating !== null ? Math.round(firstFetchedAthlete.rating).toString() : '');
      firstRatingChanged(firstFetchedAthlete.rating !== null ? Math.round(firstFetchedAthlete.rating).toString() : '');
    }
    if (secondFetchedAthlete) {
      setSecondRating(secondFetchedAthlete.rating !== null ? Math.round(secondFetchedAthlete.rating).toString() : '');
      secondRatingChanged(secondFetchedAthlete.rating !== null ? Math.round(secondFetchedAthlete.rating).toString() : '');
    }
    if (firstFetchedAthlete && secondFetchedAthlete) {
      if (!calcCustomInfo) {
        if (firstFetchedAthlete.age !== null && secondFetchedAthlete.age !== null) {
          const firstAgeIndex = ages.indexOf(firstFetchedAthlete.age);
          const secondAgeIndex = ages.indexOf(secondFetchedAthlete.age);
          if (firstAgeIndex < secondAgeIndex) {
            setCalcAge(firstFetchedAthlete.age);
          } else {
            setCalcAge(secondFetchedAthlete.age);
          }
        } else if (firstFetchedAthlete.age !== null) {
          setCalcAge(firstFetchedAthlete.age);
        } else if (secondFetchedAthlete.age !== null) {
          setCalcAge(secondFetchedAthlete.age);
        }
        if (firstFetchedAthlete.belt !== null && secondFetchedAthlete.belt !== null) {
          const firstBeltIndex = belts.indexOf(firstFetchedAthlete.belt);
          const secondBeltIndex = belts.indexOf(secondFetchedAthlete.belt);
          if (firstBeltIndex > secondBeltIndex) {
            setCalcBelt(firstFetchedAthlete.belt);
          } else {
            setCalcBelt(secondFetchedAthlete.belt);
          }
        } else if (firstFetchedAthlete.belt !== null) {
          setCalcBelt(firstFetchedAthlete.belt);
        } else if (secondFetchedAthlete.belt !== null) {
          setCalcBelt(secondFetchedAthlete.belt);
        }
        if (firstFetchedAthlete.weight !== null) {
          setCalcFirstWeight(firstFetchedAthlete.weight);
          if (secondFetchedAthlete.weight === null) {
            setCalcSecondWeight(firstFetchedAthlete.weight);
          }
        }
        if (secondFetchedAthlete.weight !== null) {
          setCalcSecondWeight(secondFetchedAthlete.weight);
          if (firstFetchedAthlete.weight === null) {
            setCalcFirstWeight(secondFetchedAthlete.weight);
          }
        }
        if (firstFetchedAthlete.weight === null && secondFetchedAthlete.weight === null) {
          setCalcFirstWeight('Heavy');
          setCalcSecondWeight('Heavy');
        }
      }
    }
  }, [firstFetchedAthlete, secondFetchedAthlete])

  useEffect(() => {
    if (firstRatingToPredict === '' || secondRatingToPredict === '') {
      setFirstExpected(null);
      setSecondExpected(null);
      return;
    }

    axios.get<PredictResponse>(`/api/athletes/predict?rating1=${firstRatingToPredict}&rating2=${secondRatingToPredict}&weight1=${calcFirstWeight}&weight2=${calcSecondWeight}&belt=${calcBelt}&age=${calcAge}`)
      .then(response => {
        const {
          first_expected,
          second_expected,
          first_win,
          first_loss,
        } = response.data;

        setFirstExpected(first_expected);
        setSecondExpected(second_expected); 
        setFirstWin(first_win);
        setFirstLoss(first_loss);
        setFirstHandicap(response.data.red_handicap);
        setSecondHandicap(response.data.blue_handicap);
      })
      .catch(error => {
        axiosErrorToast(error);
      });
  }, [firstRatingToPredict, secondRatingToPredict, calcFirstWeight, calcSecondWeight, calcBelt, calcAge])

  const firstRatingChanged = useCallback(debounce((value: string) => { setFirstRatingToPredict(value) }, 750, {trailing: true}), [])
  const secondRatingChanged = useCallback(debounce((value: string) => { setSecondRatingToPredict(value) }, 750, {trailing: true}), [])

  const getAthleteSuggestions = async (setCb: (value: string[]) => void, { value }: { value: string }) => {
    try {
      const response = await axios.get<string[]>(`/api/athletes?search=${encodeURIComponent('"' + value + '"')}&gender=${calcGender}&gi=${activeTab === 'Gi' ? 'true' : 'false'}`);
      setCb(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetAthleteSuggestions1 = useCallback(debounce(getAthleteSuggestions.bind(null, setAthleteSuggestions1), 300, {trailing: true}), [calcGender, activeTab])

  const debouncedGetAthleteSuggestions2 = useCallback(debounce(getAthleteSuggestions.bind(null, setAthleteSuggestions2), 300, {trailing: true}), [calcGender, activeTab])

  const weights = calcGender === 'Male' ? maleWeights : femaleWeights;

  // Ensure that the selected weights are valid for the current gender
  useEffect(() => {
    if (!weights.includes(calcFirstWeight)) {
      setCalcFirstWeight(weights[weights.length - 1]);
    }
    if (!weights.includes(calcSecondWeight)) {
      setCalcSecondWeight(weights[weights.length - 1]);
    }
  }, [calcGender]);

  const addPlus = (value: number) => {
    return value >= 0 ? `+${value}` : value.toString();
  }

  const formatAthleteRatings = () => {
    if (firstRatingToPredict === null || secondRatingToPredict === null) {
      return '';
    }

    let firstRating = <span>{firstRatingToPredict}</span>;
    if (firstHandicap) {
      firstRating = <span><strong className="fw-600">{Number(firstRatingToPredict) + Math.round(firstHandicap)}</strong> (+{Math.round(firstHandicap)} weight adjustment)</span>;
    }
    let secondRating = <span>{secondRatingToPredict}</span>;
    if (secondHandicap) {
      secondRating = <span><strong className="fw-600">{Number(secondRatingToPredict) + Math.round(secondHandicap)}</strong> (+{Math.round(secondHandicap)} weight adjustment)</span>;
    }

    if (!firstAthleteToFetch || !secondAthleteToFetch) {
      return <span>{firstRating} vs {secondRating}</span>
    }
    return (
      <span>
        <a href="#" onClick={e => athleteClicked(e, firstAthleteToFetch)}>{firstAthleteToFetch}</a>, {firstRating} vs <a href="#" onClick={e => athleteClicked(e, secondAthleteToFetch)}>{secondAthleteToFetch}</a>, {secondRating}
      </span>
    )
  }

  useEffect(() => {
    if (firstAthleteToFetch && secondAthleteToFetch && firstAthleteToFetch !== secondAthleteToFetch) {
      axios.get<Results>('/api/matches', {
        params: {
          gi: activeTab === 'Gi' ? 'true' : 'false',
          athlete_name: '"' + firstAthleteToFetch + '"',
          athlete_name2: '"' + secondAthleteToFetch + '"',
        }
      }).then((response: AxiosResponse<Results>) => {
        setData(response.data.rows)
      }).catch((exception) => {
        axiosErrorToast(exception)
      })
    } else {
      setData([])
    }
  }, [firstAthleteToFetch, secondAthleteToFetch]);

  const hasHistorical = useMemo(() => data.map(row => row.event).some(isHistorical), [data]);

  return (
    <section className="section has-background-light py-0" style={{ minHeight: '100vh' }}>
      <div className="container">
        <div className="box" style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.08)', borderRadius: '12px' }}>
          <GiTabs />
          <p>
            Select two athletes (or manually enter ratings) to see the predicted outcome of a match and potential Elo gain / loss.
          </p>
          <div className="calculator-header mt-4 mb-4">
            <div className="field">
              <div className="select">
                <select value={calcGender} onChange={e => setCalcGender(e.target.value)}>
                  <option>Male</option>
                  <option>Female</option>
                </select>
              </div>
            </div>
          </div>
          <div className="columns">
            <div className="column">
              <div className="calculator-header">
                <div className="field position-relative">
                  <label className="label">Search for Athlete</label>
                  <Autosuggest suggestions={athleteSuggestions1}
                               onSuggestionsFetchRequested={debouncedGetAthleteSuggestions1}
                               onSuggestionsClearRequested={() => setAthleteSuggestions1([])}
                               onSuggestionSelected={(_, { suggestion }) => {
                                 setFirstAthleteToFetch(suggestion);
                               }}
                               multiSection={false}
                               getSuggestionValue={(suggestion) => suggestion}
                               renderSuggestion={(suggestion) => suggestion}
                               inputProps={{
                                 className: "input",
                                 value: calcFirstAthlete,
                                 placeholder: "Enter Athlete Name...",
                                 onChange: (_: any, { newValue }) => {
                                   setCalcFirstAthlete(newValue)
                                   setCalcCustomInfo(false)
                                 }
                               }} />
                    {
                      calcFirstAthlete && (
                        <span className="icon is-small clear-filter-2" onClick={() => {
                          setCalcFirstAthlete('');
                          setFirstAthleteToFetch(null);
                        }}>
                          <i className="fas fa-times"></i>
                        </span>
                      )
                    }
                </div>
                <div className="field position-relative">
                  <label className="label">Search for Opponent</label>
                  <Autosuggest suggestions={athleteSuggestions2}
                               onSuggestionsFetchRequested={debouncedGetAthleteSuggestions2}
                               onSuggestionsClearRequested={() => setAthleteSuggestions2([])}
                               onSuggestionSelected={(_, { suggestion }) => {
                                 setSecondAthleteToFetch(suggestion);
                               }}
                               multiSection={false}
                               getSuggestionValue={(suggestion) => suggestion}
                               renderSuggestion={(suggestion) => suggestion}
                               inputProps={{
                                 className: "input",
                                 value: calcSecondAthlete,
                                 placeholder: "Enter Athlete Name...",
                                 onChange: (_: any, { newValue }) => {
                                   setCalcSecondAthlete(newValue)
                                   setCalcCustomInfo(false)
                                 }
                               }} />
                    {
                      calcSecondAthlete && (
                        <span className="icon is-small clear-filter-2" onClick={() => {
                          setCalcSecondAthlete('');
                          setSecondAthleteToFetch(null);
                        }}>
                          <i className="fas fa-times"></i>
                        </span>
                      )
                    }
                </div>
              </div>
            </div>
            <div className="column">
              <div className="calculator-header">
                <div className="field">
                  <label className="label">Athlete Rating</label>
                  <div className="control">
                    <input
                      className="input"
                      type="number"
                      value={firstRating}
                      min={0}
                      max={9999}
                      onChange={(e) => {
                        setFirstRating(e.target.value);
                        firstRatingChanged(e.target.value);
                      }}
                    />
                  </div>
                </div>
                <div className="field">
                  <label className="label">Opponent Rating</label>
                  <div className="control">
                    <input
                      className="input"
                      type="number"
                      value={secondRating}
                      min={0}
                      max={9999}
                      onChange={(e) => {
                        setSecondRating(e.target.value);
                        secondRatingChanged(e.target.value);
                      }}
                    />
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div className="columns">
            <div className="column is-2">
              <div className="field">
                <label className="label">Age</label>
                <div className="control">
                  <div className="select">
                    <select value={calcAge} onChange={e => {
                      setCalcAge(e.target.value)
                      setCalcCustomInfo(true)
                    }}>
                      <option>Juvenile</option>
                      <option>Adult</option>
                      <option>Master 1</option>
                      <option>Master 2</option>
                      <option>Master 3</option>
                      <option>Master 4</option>
                      <option>Master 5</option>
                      <option>Master 6</option>
                      <option>Master 7</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
            <div className="column is-2">
              <div className="field">
                <label className="label">Belt</label>
                <div className="select">
                  <select value={calcBelt} onChange={e => {
                    setCalcBelt(e.target.value)
                    setCalcCustomInfo(true)
                  }}>
                    <option value="WHITE">White</option>
                    <option value="BLUE">Blue</option>
                    <option value="PURPLE">Purple</option>
                    <option value="BROWN">Brown</option>
                    <option value="BLACK">Black</option>
                  </select>
                </div>
              </div>
            </div>
            <div className="column is-3">
              <div className="field">
                <label className="label">Athlete Weight</label>
                <div className="select">
                  <select value={calcFirstWeight} onChange={e => {
                    setCalcFirstWeight(e.target.value)
                    setCalcCustomInfo(true)
                  }}>
                  {
                    weights.map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))
                  }
                  </select>
                </div>
              </div>
            </div>
            <div className="column is-3">
              <div className="field">
                <label className="label">Opponent Weight</label>
                <div className="select">
                  <select value={calcSecondWeight} onChange={e => {
                    setCalcSecondWeight(e.target.value)
                    setCalcCustomInfo(true)
                  }}>
                  {
                    weights.map((value) => (
                      <option key={value} value={value}>{value}</option>
                    ))
                  }
                  </select>
                </div>
              </div>
            </div>
          </div>
          { (firstExpected !== null && secondExpected !== null) &&
            <>
              <h2 className="mb-4 mt-5">
                {formatAthleteRatings()}
              </h2>
              <table className="table is-fullwidth">
                <thead></thead>
                <tbody>
                  <tr>
                    <td>{firstAthleteToFetch ? firstAthleteToFetch : 'Athlete'} expected victory:</td>
                    <td className="has-text-right">{Math.round(firstExpected * 100)}%</td>
                  </tr>
                  <tr>
                    <td>{secondAthleteToFetch ? secondAthleteToFetch : 'Opponent'} expected victory:</td>
                    <td className="has-text-right">{Math.round(secondExpected * 100)}%</td>
                  </tr>
                  <tr>
                    <td>Rating change if {firstAthleteToFetch ? firstAthleteToFetch : 'athlete'} wins:</td>
                    <td className="has-text-right">{addPlus(Math.round(firstWin))}</td>
                  </tr>
                  <tr>
                    <td>Rating change if {secondAthleteToFetch ? secondAthleteToFetch : 'opponent'} wins:</td>
                    <td className="has-text-right">{addPlus(Math.round(firstLoss))}</td>
                  </tr>
                </tbody>
              </table>
              <div className="card pt-1 pr-4 pb-4 mb-5">
                <div className="content">
                  <ul>
                    {
                      (firstFetchedAthlete?.belt && secondFetchedAthlete?.belt && firstFetchedAthlete.belt !== secondFetchedAthlete.belt) &&
                      <li >This matchup is across belts. Athletes will receive additional promotion points as they get promoted which could change the projected outcome.</li>
                    }
                    <li>Athletes with provisional ratings (six or fewer matches) will gain / lose more Elo than shown above.</li>
                  </ul>
                </div>
              </div>
              {
                data && data.length > 0 && (
                  <div>
                    <p className="has-text-weight-bold mb-3">
                      Match history:
                    </p>
                    <DBTableRows data={data}
                                 loading={false}
                                 noLinks={true}
                                 divisionBracketClicked={divisionBracketClicked}/>
                    {
                      hasHistorical && (
                        <div className="notification is-historical">
                          Match data before December 2024 may be incomplete or inaccurate
                        </div>
                      )
                    }
                  </div>
                )
              }
            </>
          }
        </div>
      </div>
    </section>
  )
}

export default Calculator
