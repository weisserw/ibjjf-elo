import { useState, useEffect, useCallback } from 'react'
import axios, { AxiosResponse } from 'axios';
import { debounce, set } from 'lodash'
import "./EloTable.css"

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
  name: 'All',
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

interface Row {
  rank: number
  name: string
  rating: number
}

interface EloTableProps {
  gi: boolean
}

function EloTable(props: EloTableProps) {
  const [gender, setGender] = useState('Male')
  const [age, setAge] = useState('Adult')
  const [belt, setBelt] = useState('BLACK')
  const [weight, setWeight] = useState('')
  const [nameFilter, setNameFilter] = useState('')
  const [nameFilterSearch, setNameFilterSearch] = useState('')
  const [loading, setLoading] = useState(false)
  const [data, setData] = useState<Row[]>([])

  useEffect(() => {
    setLoading(true)
    axios.get<Row[]>('/api/top', {
      params: {
        gender,
        age,
        belt,
        weight,
        name: nameFilterSearch,
        gi: props.gi ? 'true' : 'false'
      }
    }).then((response: AxiosResponse<Row[]>) => {
      setData(response.data)
      setLoading(false)
    }).catch((exception) => {
      console.error(exception)
      setLoading(false)
    })
  }, [gender, age, belt, weight, nameFilterSearch, props.gi]);

  const isJuvenileAge = (age: string) => {
    return age.startsWith('Juvenile')
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

  const debouncedSetNameFilterSearch = useCallback(
    debounce((value: string) => setNameFilterSearch(value), 300),
    []
  );

  const onNameFilterChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setNameFilter(event.target.value)
    debouncedSetNameFilterSearch(event.target.value)
  }

  const ranks = isJuvenileAge(age) ? juvenileRanks : adultRanks;

  const weights = gender === 'Male' ? maleWeights : femaleWeights;

  return (
    <div>
      <div className="columns is-mobile">
        <div className="column">
          <div className="field is-horizontal">
            <div className="field-label">
              <label className="label">Gender:</label>
            </div>
            <div className="field-body">
              <div className="field">
                <div className="control">
                  <div className="select">
                    <select value={gender} onChange={onGenderChange}>
                      <option>Male</option>
                      <option>Female</option>
                    </select>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div className="column">
          <div className="field is-horizontal">
            <div className="field-label">
              <label className="label">Age:</label>
            </div>
            <div className="field-body">
              <div className="field">
                <div className="control">
                  <div className="select">
                    <select value={age} onChange={onAgeChange}>
                      <option>Juvenile 1</option>
                      <option>Juvenile 2</option>
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
          </div>
        </div>
        <div className="column">
          <div className="field is-horizontal">
            <div className="field-label">
              <label className="label">Belt:</label>
            </div>
            <div className="field-body">
              <div className="field">
                <div className="control">
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
            </div>
          </div>
        </div>
        <div className="column">
          <div className="field is-horizontal">
            <div className="field-label">
              <label className="label">Weight:</label>
            </div>
            <div className="field-body">
              <div className="field">
                <div className="control">
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
            </div>
          </div>
        </div>
      </div>
      <div>
        <div className="field">
          <div className="control">
            <input className="input" type="text" placeholder="Enter name..." value={nameFilter} onChange={onNameFilterChange} />
          </div>
        </div>
        <table className="table is-fullwidth is-striped">
          <thead>
            <tr>
              <th>#</th>
              <th>↑↓</th>
              <th>Name</th>
              <th>Rating</th>
              <th>+/-</th>
            </tr>
          </thead>
          <tbody>
            {
              loading && (
                <tr>
                  <td colSpan={5} className="empty-row">
                    <div className="columns is-centered">
                      <div className="column is-narrow">
                        <div className="loader"></div>
                      </div>
                    </div>
                  </td>
                </tr>
              )
            }
            {
              !loading && data.length === 0 && (
                <tr>
                  <td colSpan={5} className="empty-row">
                    <div className="columns is-centered">
                      No data found
                    </div>
                  </td>
                </tr>
              )
            }
            {
              !loading && !!data.length && data.map((row: Row) => (
                <tr key={row.rank}>
                  <td>{row.rank}</td>
                  <td>&nbsp;</td>
                  <td>{row.name}</td>
                  <td>{row.rating}</td>
                  <td>&nbsp;</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default EloTable