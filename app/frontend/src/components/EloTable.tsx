import { useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { useAppContext } from '../AppContext';
import DBPagination from './DBPagination';
import EloFilters from './EloFilters';
import SearchEloTable from './SearchEloTable';
import classNames from 'classnames';
import { axiosErrorToast, immatureClass } from '../utils';

import "./EloTable.css"
import './ResponsiveTable.css'

interface Row {
  rank: number
  previous_rank: number | null
  name: string
  rating: number
  match_count: number
  previous_rating: number | null
  previous_match_count: number | null
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

  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [data, setData] = useState<Row[]>([])
  const [totalPages, setTotalPages] = useState(1)

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
      axiosErrorToast(exception)
      setLoading(false)
      setReloading(false)
    })
  }, [gender, age, belt, weight, changed, nameFilter, gi, page]);

  const onNameClick = (e: React.MouseEvent, name: string) => {
    e.preventDefault();
  
    setFilters({ athlete_name: '"' + name + '"' });
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
    if (immatureClass(row.match_count) === 'very-immature') {
      return '';
    }
    if (row.previous_rank === null || immatureClass(row.previous_match_count) === 'very-immature') {
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
      return 'has-text-right-desktop-only new-marker-td';
    }
    if (start === null || start === end) {
      return 'has-text-right-desktop-only';
    }

    let diff = end - start;
    if (reverse) { diff *= -1; }

    if (diff > 0) {
      return 'has-text-right-desktop-only has-text-success';
    } else {
      return 'has-text-right-desktop-only has-text-danger';
    }
  }

  const rowTooltip = (row: Row) => {
    const immature = immatureClass(row.match_count);
    if (immature === '') {
      return undefined;
    }
    if (immature === 'very-immature') {
      return `Athlete's rating is provisional due to insufficient matches (${row.match_count})`;
    }
    return `Athlete's rating is semi-provisional due to insufficient matches (${row.match_count})`;
  }

  return (
    <div className="elo-container">
      <div className="elo-sub-container">
        <EloFilters />
        <SearchEloTable nameFilter={nameFilter} setNameFilter={setNameFilter} />
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
                  <th className="has-text-right-desktop-only">#</th>
                  <th className="has-text-right-desktop-only">↑↓</th>
                  <th>Name</th>
                  <th className="has-text-right-desktop-only">Rating</th>
                  <th className="has-text-right-desktop-only">+/-</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {
                  data.length === 0 && (
                    <tr>
                      <td colSpan={6} className="empty-row">
                        No matching competitors in selected division. Try changing the category filters or use the{' '}
                        <Link to="/database">Database</Link>
                        {' '}page to perform a global search.
                      </td>
                    </tr>
                  )
                }
                {
                  !!data.length && data.map((row: Row, index) => (
                    <tr key={index}>
                      <td className="" data-label="Rank">{
                        immatureClass(row.match_count) !== 'very-immature' && row.rank
                      }</td>
                      <td className={changeClass(row.previous_rank, row.rank, true)} data-label="Rank Change">{rankChange(row)}</td>
                      <td data-label="Name">
                        <a href="#" onClick={e => onNameClick(e, row.name)}>
                          {row.name}
                        </a>
                      </td>
                      <td className={"has-text-right-desktop-only " + immatureClass(row.match_count)} data-label="Rating">{row.rating}</td>
                      <td className={changeClass(row.previous_rating, row.rating, false)} data-label="Rating Change">{ratingChange(row)}</td>
                      <td className={classNames("has-text-centered-tablet-only", {"has-tooltip-multiline has-tooltip-left": immatureClass(row.match_count) !== ''})} data-tooltip={rowTooltip(row)} data-label="Status">
                        {
                          immatureClass(row.match_count) === 'very-immature' ? 
                            <span className="very-immature-bullet">&nbsp;</span> : (
                              immatureClass(row.match_count) === 'immature' &&
                              <span className="immature-bullet">&nbsp;</span>
                            )
                        }
                      </td>
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