import { useAppContext } from "../AppContext"
import { ages } from "../utils"

import "./EloFilters.css"

const juvenileRanks = [
  'White',
  'Blue',
  'Purple',
]

const juvenileRanksValues = juvenileRanks.map(rank => rank.toUpperCase())

const adultRanks = [
  'White',
  'Blue',
  'Purple',
  'Brown',
  'Black',
]

const adultRanksValues = adultRanks.map(rank => rank.toUpperCase())

const femaleWeights = [{
  name: 'P4P',
  value: ''
}, {
  name: 'Rooster',
  value: 'Rooster'
}, {
  name: 'Light Feather',
  value: 'Light Feather'
}, {
  name: 'Feather',
  value: 'Feather'
}, {
  name: 'Light',
  value: 'Light'
}, {
  name: 'Middle',
  value: 'Middle'
}, {
  name: 'Medium Heavy',
  value: 'Medium Heavy'
}, {
  name: 'Heavy',
  value: 'Heavy'
}, {
  name: 'Super Heavy',
  value: 'Super Heavy'
}];

const maleWeights = femaleWeights.concat([{
  name: 'Ultra Heavy',
  value: 'Ultra Heavy'
}]);

function EloFilters() {
  const {
    rankingGender: gender,
    rankingAge: age,
    rankingBelt: belt,
    rankingWeight: weight,
    rankingChanged: changed,
    rankingUpcoming: upcoming,
    setRankingGender: setGender,
    setRankingAge: setAge,
    setRankingBelt: setBelt,
    setRankingWeight: setWeight,
    setRankingChanged: setChanged,
    setRankingUpcoming: setUpcoming,
  } = useAppContext();

  const isJuvenileAge = (age: string) => {
    return age === 'Juvenile'
  }

  const isAdultAge = (age: string) => {
    return !isJuvenileAge(age)
  }

  const onGenderChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setGender(event.target.value)

    if (event.target.value === 'Female' && weight === 'Ultra Heavy') {
      setWeight('')
    }
  }

  const defaultBelt = (age: string) => {
    if (isAdultAge(age)) {
      return 'BLACK';
    } else {
      return 'BLUE';
    }
  }

  const onAgeChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setAge(event.target.value)

    if ((isJuvenileAge(event.target.value) && juvenileRanksValues.indexOf(belt) !== -1)
      || (isAdultAge(event.target.value) && adultRanksValues.indexOf(belt) === -1)) {
        setBelt(defaultBelt(event.target.value))
    }
  }

  const onBeltChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setBelt(event.target.value)
  }

  const onWeightChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    setWeight(event.target.value)
  }

  const ranks = isJuvenileAge(age) ? juvenileRanks : adultRanks;

  const weights = gender === 'Male' ? maleWeights : femaleWeights;

  return (
    <div className="columns is-mobile is-multiline">
      <div className="column is-third-mobile">
        <div className="field mobile-margin">
          <label className="label">Gender</label>
          <div className="select">
            <select value={gender} onChange={onGenderChange}>
              <option>Male</option>
              <option>Female</option>
            </select>
          </div>
        </div>
      </div>
      <div className="column is-third-mobile">
        <div className="field">
          <label className="label">Age</label>
          <div className="select">
            <select value={age} onChange={onAgeChange}>
              {
                ages.map(age => (
                  <option key={age} value={age}>{age}</option>
                ))
              }
            </select>
          </div>
        </div>
      </div>
      <div className="column is-third-mobile">
        <div className="field">
          <label className="label">Belt</label>
          <div className="select">
            <select value={belt} onChange={onBeltChange}>
              {
                ranks.map(rank => (
                  <option key={rank} value={rank.toUpperCase()}>{rank}</option>
                ))
              }
            </select>
          </div>
        </div>
      </div>
      <div className="column is-half-mobile">
        <div className="field mobile-margin">
          <label className="label">Weight</label>
          <div className="select">
            <select value={weight} onChange={onWeightChange}>
              {
                weights.map(({ name, value }) => (
                  <option key={value} value={value}>{name}</option>
                ))
              }
            </select>
          </div>
        </div>
      </div>
      <div className="column is-half-mobile">
        <div className="field checkbox-margin">
          <div className="control">
            <label className="checkbox">
              <input type="checkbox" checked={upcoming} onChange={() => setUpcoming(!upcoming)} />
              &nbsp;Upcoming
            </label>
          </div>
          <div className="control mt-3">
            <label className="checkbox">
              <input type="checkbox" checked={changed} onChange={() => setChanged(!changed)} />
              &nbsp;Changed
            </label>
          </div>
        </div>
      </div>
    </div>
  );
}

export default EloFilters;