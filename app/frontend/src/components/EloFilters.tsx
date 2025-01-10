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

interface EloFiltersProps {
  gender: string;
  age: string;
  belt: string;
  weight: string;

  setGender: (value: string) => void;
  setAge: (value: string) => void;
  setBelt: (value: string) => void;
  setWeight: (value: string) => void;
}

function EloFilters(props: EloFiltersProps) {
  const isJuvenileAge = (age: string) => {
    return age === 'Juvenile'
  }

  const isAdultAge = (age: string) => {
    return !isJuvenileAge(age)
  }

  const onGenderChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    props.setGender(event.target.value)

    if (event.target.value === 'Female' && props.weight === 'Ultra Heavy') {
      props.setWeight('')
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
    props.setAge(event.target.value)

    if ((isJuvenileAge(event.target.value) && juvenileRanksValues.indexOf(props.belt) !== -1)
      || (isAdultAge(event.target.value) && adultRanksValues.indexOf(props.belt) === -1)) {
        props.setBelt(defaultBelt(event.target.value))
    }
  }

  const onBeltChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    props.setBelt(event.target.value)
  }

  const onWeightChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    props.setWeight(event.target.value)
  }

  const ranks = isJuvenileAge(props.age) ? juvenileRanks : adultRanks;

  const weights = props.gender === 'Male' ? maleWeights : femaleWeights;

  return (
    <div className="columns is-mobile is-multiline">
      <div className="column is-half-mobile">
        <div className="field mobile-margin">
          <label className="label">Gender</label>
          <div className="select">
            <select value={props.gender} onChange={onGenderChange}>
              <option>Male</option>
              <option>Female</option>
            </select>
          </div>
        </div>
      </div>
      <div className="column is-half-mobile">
        <div className="field">
          <label className="label">Age</label>
          <div className="select">
            <select value={props.age} onChange={onAgeChange}>
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
      <div className="column is-half-mobile">
        <div className="field mobile-margin">
          <label className="label">Belt</label>
          <div className="select">
            <select value={props.belt} onChange={onBeltChange}>
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
        <div className="field">
          <label className="label">Weight</label>
          <div className="select">
            <select value={props.weight} onChange={onWeightChange}>
              {
                weights.map(({ name, value }) => (
                  <option key={value} value={value}>{name}</option>
                ))
              }
            </select>
          </div>
        </div>
      </div>
    </div>
  );
}

export default EloFilters;