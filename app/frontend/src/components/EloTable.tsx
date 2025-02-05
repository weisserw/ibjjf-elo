import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { debounce } from 'lodash';
import { useAppContext } from '../AppContext';
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

function EloTable() {
  const {
    activeTab,
    rankingGender: gender,
    rankingAge: age,
    rankingBelt: belt,
    rankingWeight: weight,
    rankingChanged: changed,
    rankingNameFilter: nameFilter,
    rankingPage: page,
    setRankingNameFilter: setNameFilter,
    setRankingPage: setPage,
    setFilters,
    setOpenFilters,
  } = useAppContext();

  const [nameFilterSearch, setNameFilterSearch] = useState(nameFilter)
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [data, setData] = useState<Row[]>([])
  const [totalPages, setTotalPages] = useState(1)
  const [athleteSuggestions, setAthleteSuggestions] = useState<string[]>([])

  const navigate = useNavigate()

  const gi = activeTab === 'Gi'

  useEffect(() => {
    setReloading(true)
    axios.get<Results>('/api/top', {
      params: {
        gender: gender,
        age: age,
        belt: belt,
        weight: weight,
        changed: changed ? 'true' : 'false',
        name: nameFilter,
        gi: gi ? 'true' : 'false',
        page: page,
      }
    }).then((response: AxiosResponse<Results>) => {
      setData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setLoading(false)
      setReloading(false)

      if (response.data.totalPages < page) {
        setPage(1)
      }
    }).catch((exception) => {
      console.error(exception)
      setLoading(false)
      setReloading(false)
    })
  }, [gender, age, belt, weight, changed, nameFilter, gi, page]);

  const getAthleteSuggestions = async ({ value }: { value: string }) => {
    const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
    setAthleteSuggestions(response.data);
  }

  const debouncedSetNameFilter = useCallback(
    debounce((value: string) => setNameFilter(value), 750),
    []
  );

  const onNameFilterChange = (value: string) => {
    setNameFilterSearch(value)
    debouncedSetNameFilter(value)
  }

  const onNameClick = (e: React.MouseEvent, name: string) => {
    e.preventDefault();
  
    setFilters({ athlete_name: name });
    setOpenFilters({athlete: true, event: false, division: false});
    navigate('/database');
  };

  const onFirstPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    setPage(1)
  }

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

  const rankChange = (row: Row) => {
    if (row.previous_rank === null) {
      return <span className="new-marker">New</span>;
    }
    if (ratingChange(row) === '' || (row.rank === row.previous_rank)) {
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
    if (start === null && reverse) {
      return 'has-text-right new-marker-td';
    }
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
    <div className="elo-container">
      <div className="elo-sub-container">
        <EloFilters />
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
        {
          loading && (
            <div className="table-loader">
              <div className="loader"></div>
            </div>
          )
        }
        {
          !loading && (
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
                  data.length === 0 && (
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
                  !!data.length && data.map((row: Row, index) => (
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
          )
        }
        {
          !loading && data.length > 0 && (
            <DBPagination loading={reloading}
                          page={page}
                          showPages={true}
                          totalPages={totalPages}
                          onFirstPage={onFirstPage}
                          onNextPage={onNextPage}
                          onPreviousPage={onPreviousPage}
                          onPageClick={onPageClick} />
          )
        }
      </div>
    </div>
  )
}

export default EloTable