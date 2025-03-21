import { useState, useCallback, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import GiTabs from "./GiTabs"
import Autosuggest from 'react-autosuggest'
import axios from 'axios'
import { debounce } from 'lodash'
import { axiosErrorToast, ages } from '../utils'
import { useAppContext } from '../AppContext'

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
  const [age, setAge] = useState('Adult')
  const [belt, setBelt] = useState('BLACK')
  const [firstWeight, setFirstWeight] = useState('Heavy')
  const [secondWeight, setSecondWeight] = useState('Heavy')
  const [firstExpected, setFirstExpected] = useState<number | null>(0.0)
  const [secondExpected, setSecondExpected] = useState<number | null>(0.0)
  const [firstWin, setFirstWin] = useState(0)
  const [firstLoss, setFirstLoss] = useState(0)
  const [firstHandicap, setFirstHandicap] = useState(0)
  const [secondHandicap, setSecondHandicap] = useState(0)

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
  } = useAppContext();

  const navigate = useNavigate();

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
      if (firstFetchedAthlete.age !== null && secondFetchedAthlete.age !== null) {
        const firstAgeIndex = ages.indexOf(firstFetchedAthlete.age);
        const secondAgeIndex = ages.indexOf(secondFetchedAthlete.age);
        if (firstAgeIndex < secondAgeIndex) {
          setAge(firstFetchedAthlete.age);
        } else {
          setAge(secondFetchedAthlete.age);
        }
      } else if (firstFetchedAthlete.age !== null) {
        setAge(firstFetchedAthlete.age);
      } else if (secondFetchedAthlete.age !== null) {
        setAge(secondFetchedAthlete.age);
      }
      if (firstFetchedAthlete.belt !== null && secondFetchedAthlete.belt !== null) {
        const firstBeltIndex = belts.indexOf(firstFetchedAthlete.belt);
        const secondBeltIndex = belts.indexOf(secondFetchedAthlete.belt);
        if (firstBeltIndex > secondBeltIndex) {
          setBelt(firstFetchedAthlete.belt);
        } else {
          setBelt(secondFetchedAthlete.belt);
        }
      } else if (firstFetchedAthlete.belt !== null) {
        setBelt(firstFetchedAthlete.belt);
      } else if (secondFetchedAthlete.belt !== null) {
        setBelt(secondFetchedAthlete.belt);
      }
      if (firstFetchedAthlete.weight !== null) {
        setFirstWeight(firstFetchedAthlete.weight);
        if (secondFetchedAthlete.weight === null) {
          setSecondWeight(firstFetchedAthlete.weight);
        }
      }
      if (secondFetchedAthlete.weight !== null) {
        setSecondWeight(secondFetchedAthlete.weight);
        if (firstFetchedAthlete.weight === null) {
          setFirstWeight(secondFetchedAthlete.weight);
        }
      }
      if (firstFetchedAthlete.weight === null && secondFetchedAthlete.weight === null) {
        setFirstWeight('Heavy');
        setSecondWeight('Heavy');
      }
    }
  }, [firstFetchedAthlete, secondFetchedAthlete])

  useEffect(() => {
    if (firstRatingToPredict === '' || secondRatingToPredict === '') {
      setFirstExpected(null);
      setSecondExpected(null);
      return;
    }

    axios.get<PredictResponse>(`/api/athletes/predict?rating1=${firstRatingToPredict}&rating2=${secondRatingToPredict}&weight1=${firstWeight}&weight2=${secondWeight}&belt=${belt}&age=${age}`)
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
  }, [firstRatingToPredict, secondRatingToPredict, firstWeight, secondWeight, belt, age])

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
    if (!weights.includes(firstWeight)) {
      setFirstWeight(weights[weights.length - 1]);
    }
    if (!weights.includes(secondWeight)) {
      setSecondWeight(weights[weights.length - 1]);
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

  return (
    <div className="container calculator-container">
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
                  <select value={age} onChange={e => setAge(e.target.value)}>
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
                <select value={belt} onChange={e => setBelt(e.target.value)}>
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
                <select value={firstWeight} onChange={e => setFirstWeight(e.target.value)}>
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
                <select value={secondWeight} onChange={e => setSecondWeight(e.target.value)}>
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
            <div className="card pt-1 pr-4 pb-4">
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
          </>
        }
    </div>
  )
}

export default Calculator
