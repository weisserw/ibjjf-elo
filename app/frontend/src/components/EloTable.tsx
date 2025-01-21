import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { debounce } from 'lodash'
import { FilterValues, type OpenFilters } from './DBFilters';
import DBPagination from './DBPagination';
import EloFilters from './EloFilters';
import Autosuggest from 'react-autosuggest';
import "./EloTable.css"

interface Row {
  rank: number
  previous_rank: number | null
  name: string
  rating: number
  previous_rating: number | null
}

interface Results {
  rows: Row[]
  totalPages: number
}

interface EloTableProps {
  gi: boolean
  gender: string
  age: string
  belt: string
  weight: string
  changed: boolean
  nameFilter: string
  page: number
  setGender: (value: string) => void
  setAge: (value: string) => void
  setBelt: (value: string) => void
  setWeight: (value: string) => void
  setChanged: (value: boolean) => void
  setNameFilter: (name: string) => void
  setFilters: (filters: FilterValues) => void
  setOpenFilters: (openFilters: OpenFilters) => void
  setPage: (page: number) => void
}

function EloTable(props: EloTableProps) {
  const [nameFilterSearch, setNameFilterSearch] = useState(props.nameFilter)
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [data, setData] = useState<Row[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [athleteSuggestions, setAthleteSuggestions] = useState<string[]>([])

  const navigate = useNavigate()

  useEffect(() => {
    setReloading(true)
    axios.get<Results>('/api/top', {
      params: {
        gender: props.gender,
        age: props.age,
        belt: props.belt,
        weight: props.weight,
        changed: props.changed ? 'true' : 'false',
        name: props.nameFilter,
        gi: props.gi ? 'true' : 'false',
        page: props.page,
      }
    }).then((response: AxiosResponse<Results>) => {
      setData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setLoading(false)
      setReloading(false)

      if (response.data.totalPages < props.page) {
        props.setPage(1)
      }
    }).catch((exception) => {
      console.error(exception)
      setLoading(false)
      setReloading(false)
    })
  }, [props.gender, props.age, props.belt, props.weight, props.changed, props.nameFilter, props.gi, props.page]);

  const getAthleteSuggestions = async ({ value }: { value: string }) => {
    const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
    setAthleteSuggestions(response.data);
  }

  const debouncedSetNameFilter = useCallback(
    debounce((value: string) => props.setNameFilter(value), 750),
    []
  );

  const onNameFilterChange = (value: string) => {
    setNameFilterSearch(value)
    debouncedSetNameFilter(value)
  }

  const onNameClick = (e: React.MouseEvent, name: string) => {
    e.preventDefault();
  
    props.setFilters({ athlete_name: name });
    props.setOpenFilters({athlete: true, event: false, division: false});
    navigate('/database');
  };

  const onNextPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    if (props.page < totalPages) {
      props.setPage(props.page + 1)
    }
  }

  const onPreviousPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    if (props.page > 1) {
      props.setPage(props.page - 1)
    }
  }

  const onPageClick = (pageNumber: number, event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    props.setPage(pageNumber)
  }

  const rankChange = (row: Row) => {
    if (ratingChange(row) === '' || row.previous_rank === null || (row.rank === row.previous_rank)) {
      return '';
    }

    const diff = row.rank - row.previous_rank;

    if (diff < 0) {
      return `↑${(-diff).toLocaleString()}`;
    } else {
      return `↓${diff.toLocaleString()}`;
    }
  }

  const ratingChange = (row: Row) => {
    if (row.previous_rating === null || (row.rating === row.previous_rating)) {
      return '';
    }

    const diff = row.rating - row.previous_rating;

    if (diff > 0) {
      return `+${diff.toLocaleString()}`;
    } else {
      return diff.toLocaleString();
    }
  }

  const changeClass = (start: number | null, end: number, reverse: boolean) => {
    if (start === null || start === end) {
      return 'has-text-right';
    }

    let diff = end - start;
    if (reverse) { diff *= -1; }

    if (diff > 0) {
      return 'has-text-right has-text-success';
    } else {
      return 'has-text-right has-text-danger';
    }
  }


  return (
    <div>
      <EloFilters gender={props.gender}
                  setGender={props.setGender}
                  age={props.age}
                  setAge={props.setAge}
                  belt={props.belt}
                  setBelt={props.setBelt}
                  weight={props.weight}
                  setWeight={props.setWeight}
                  changed={props.changed}
                  setChanged={props.setChanged} />
      <div>
        <div className="field">
          <div className="control has-icons-left">
            <Autosuggest suggestions={athleteSuggestions}
                         onSuggestionsFetchRequested={getAthleteSuggestions}
                         onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                         multiSection={false}
                         getSuggestionValue={(suggestion) => suggestion}
                         renderSuggestion={(suggestion) => suggestion}
                         inputProps={{
                           className: "input",
                           value: nameFilterSearch,
                           placeholder: "Search Within Division",
                           onChange: (_: any, { newValue }) => {
                            onNameFilterChange(newValue)
                           }
                         }} />
            <span className="icon is-small is-left">
              <i className="fas fa-filter"></i>
            </span>
          </div>
        </div>
        <table className="table is-fullwidth table-margin">
          <thead>
            <tr>
              <th className="has-text-right">#</th>
              <th className="has-text-right">↑↓</th>
              <th>Name</th>
              <th className="has-text-right">Rating</th>
              <th className="has-text-right">+/-</th>
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
                  <td className={changeClass(row.previous_rank, row.rank, true)}>{rankChange(row)}</td>
                  <td>
                    <a href="#" onClick={e => onNameClick(e, row.name)}>
                      {row.name}
                    </a>
                  </td>
                  <td className="has-text-right">{row.rating}</td>
                  <td className={changeClass(row.previous_rating, row.rating, false)}>{ratingChange(row)}</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
      {
        !loading && data.length > 0 && (
          <DBPagination loading={reloading} page={props.page} totalPages={totalPages} onNextPage={onNextPage} onPreviousPage={onPreviousPage} onPageClick={onPageClick} />
        )
      }
    </div>
  )
}

export default EloTable