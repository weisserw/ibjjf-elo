import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { debounce } from 'lodash'
import { FilterValues, type OpenFilters } from './DBFilters';
import DBPagination from './DBPagination';
import Autosuggest from 'react-autosuggest';
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

interface Row {
  rank: number
  name: string
  rating: number
}

interface Results {
  rows: Row[]
  totalPages: number
}

interface EloTableProps {
  gi: boolean
  setFilters: (filters: FilterValues) => void
  setOpenFilters: (openFilters: OpenFilters) => void
}

function EloTable(props: EloTableProps) {
  const [gender, setGender] = useState('Male')
  const [age, setAge] = useState('Adult')
  const [belt, setBelt] = useState('BLACK')
  const [weight, setWeight] = useState('')
  const [nameFilter, setNameFilter] = useState('')
  const [nameFilterSearch, setNameFilterSearch] = useState('')
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [data, setData] = useState<Row[]>([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [athleteSuggestions, setAthleteSuggestions] = useState<string[]>([])

  const navigate = useNavigate()

  useEffect(() => {
    setReloading(true)
    axios.get<Results>('/api/top', {
      params: {
        gender,
        age,
        belt,
        weight,
        name: nameFilterSearch,
        gi: props.gi ? 'true' : 'false',
        page
      }
    }).then((response: AxiosResponse<Results>) => {
      setData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setLoading(false)
      setReloading(false)

      if (response.data.rows.length === 0 && page > 1) {
        setPage(1)
      }
    }).catch((exception) => {
      console.error(exception)
      setLoading(false)
      setReloading(false)
    })
  }, [gender, age, belt, weight, nameFilterSearch, props.gi, page]);

  const getAthleteSuggestions = async ({ value }: { value: string }) => {
    const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
    setAthleteSuggestions(response.data);
  }

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
    debounce((value: string) => setNameFilterSearch(value), 750),
    []
  );

  const onNameFilterChange = (value: string) => {
    setNameFilter(value)
    debouncedSetNameFilterSearch(value)
  }

  const onNameClick = (e: React.MouseEvent, name: string) => {
    e.preventDefault();
  
    props.setFilters({ athlete_name: name });
    props.setOpenFilters({athlete: true, event: false, division: false});
    navigate('/database');
  };

  const onNextPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    if (page < totalPages) {
      setPage(page + 1)
    }
  }

  const onPreviousPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    if (page > 1) {
      setPage(page - 1)
    }
  }

  const onPageClick = (pageNumber: number, event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    setPage(pageNumber)
  }

  const ranks = isJuvenileAge(age) ? juvenileRanks : adultRanks;

  const weights = gender === 'Male' ? maleWeights : femaleWeights;

  return (
    <div>
      <div className="columns is-mobile is-multiline">
        <div className="column is-half-mobile">
          <div className="field">
            <label className="label">Gender</label>
            <div className="select">
              <select value={gender} onChange={onGenderChange}>
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
        <div className="column is-half-mobile">
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
          <div className="field">
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
      </div>
      <div>
        <div className="field">
          <div className="control ">
            <Autosuggest suggestions={athleteSuggestions}
                         onSuggestionsFetchRequested={getAthleteSuggestions}
                         onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                         multiSection={false}
                         getSuggestionValue={(suggestion) => suggestion}
                         renderSuggestion={(suggestion) => suggestion}
                         inputProps={{
                           className: "input",
                           value: nameFilter,
                           placeholder: "Enter Name...",
                           onChange: (_: any, { newValue }) => {
                            onNameFilterChange(newValue)
                           }
                         }} />
          </div>
        </div>
        <table className="table is-fullwidth table-margin">
          <thead>
            <tr>
              <th className="has-text-right">#</th>
              <th>Name</th>
              <th className="has-text-right">Rating</th>
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
              !loading && !!data.length && data.map((row: Row, index) => (
                <tr key={index}>
                  <td className="has-text-right">{row.rank}</td>
                  <td>
                    <a href="#" onClick={e => onNameClick(e, row.name)}>
                      {row.name}
                    </a>
                  </td>
                  <td className="has-text-right">{row.rating}</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
      {
        !loading && data.length > 0 && (
          <DBPagination loading={reloading} page={page} totalPages={totalPages} onNextPage={onNextPage} onPreviousPage={onPreviousPage} onPageClick={onPageClick} />
        )
      }
    </div>
  )
}

export default EloTable