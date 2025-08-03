import { useState, useEffect, useCallback } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { debounce } from 'lodash';
import { useAppContext } from '../AppContext';
import DBPagination from './DBPagination';
import EloFilters from './EloFilters';
import Autosuggest from 'react-autosuggest';
import classNames from 'classnames';
import dayjs from 'dayjs';
import { Tooltip } from 'react-tooltip';
import { axiosErrorToast, immatureClass } from '../utils';

import "./EloTable.css"

interface Registration {
  event_name: string
  event_id: string
  division: string
  event_start_date: string
  event_end_date: string
  link: string
}

interface Row {
  rank: number
  previous_rank: number | null
  name: string
  rating: number
  match_count: number
  previous_rating: number | null
  previous_match_count: number | null
  registrations: Registration[]
}

interface Results {
  rows: Row[]
  totalPages: number
}

function formatEventDates(startDate: string, endDate: string): string {
    if (!startDate || !endDate) {
        return "";
    }
    const start = dayjs(startDate);
    const end = dayjs(endDate);

    if (!start.isValid() || !end.isValid()) {
        return "";
    }

    if (start.isSame(end, 'day')) {
        // Example: Oct 15
        return `${start.format('MMM')} ${start.date()}`;
    }
    if (start.month() === end.month() && start.year() === end.year()) {
        // Example: Oct 15 - 17
        return `${start.format('MMM')} ${start.date()} - ${end.date()}`;
    }
    // Example: Oct 28 - Nov 2
    return `${start.format('MMM')} ${start.date()} - ${end.format('MMM')} ${end.date()}`;
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
    setBracketSelectedEvent,
    setBracketSelectedCategory,
    setBracketRegistrationSelectedUpcomingLink,
    setBracketRegistrationSelectedCategory,
    setBracketActiveTab,
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
      axiosErrorToast(exception)
      setLoading(false)
      setReloading(false)
    })
  }, [gender, age, belt, weight, changed, nameFilter, gi, page]);

  const getAthleteSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
      setAthleteSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetAthleteSuggestions = useCallback(debounce(getAthleteSuggestions, 300, {trailing: true}), []);

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

  const onRegistrationClicked = (e: React.MouseEvent, registration: Registration) => {
    e.preventDefault();

    // if event start date is in less than 24 hours, go to live brackets
    const eventStartDate = new Date(registration.event_start_date);
    if (eventStartDate.getTime() - new Date().getTime() < 24 * 60 * 60 * 1000) {
      setBracketSelectedEvent(registration.event_id);
      setBracketSelectedCategory(registration.division);
      setBracketActiveTab('Live');
    } else {
      setBracketRegistrationSelectedUpcomingLink(registration.link);
      setBracketRegistrationSelectedCategory(registration.division);
      setBracketActiveTab('Registrations');
    }

    navigate('/brackets');
  }

  return (
    <div className="elo-container">
      <div className="elo-sub-container">
        <EloFilters />
        <div className="field position-relative">
          <div className="control has-icons-left">
            <Autosuggest suggestions={athleteSuggestions}
                          onSuggestionsFetchRequested={debouncedGetAthleteSuggestions}
                          onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                          multiSection={false}
                          getSuggestionValue={(suggestion) => '"' + suggestion + '"'}
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
          {
            nameFilterSearch && (
              <span className="icon is-small clear-filter" onClick={() => {
                setNameFilterSearch('')
                setNameFilter('')
              }}>
                <i className="fas fa-times"></i>
              </span>
            )
          }
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
                  <th className="cell-no-padding"></th>
                  <th className="cell-no-padding"></th>
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
                      <td className="has-text-right">{
                        immatureClass(row.match_count) !== 'very-immature' && row.rank
                      }</td>
                      <td className={changeClass(row.previous_rank, row.rank, true)}>{rankChange(row)}</td>
                      <td>
                        <a href="#" onClick={e => onNameClick(e, row.name)}>
                          {row.name}
                        </a>
                      </td>
                      <td className={"has-text-right " + immatureClass(row.match_count)}>
                        {row.rating}
                      </td>
                      <td className={changeClass(row.previous_rating, row.rating, false)}>{ratingChange(row)}</td>
                      <td className={classNames("has-text-centered cell-no-padding", {"has-cursor-pointer": rowTooltip(row)})} data-tooltip-id="elo-tooltip" data-tooltip-content={rowTooltip(row)}>
                        {
                          immatureClass(row.match_count) === 'very-immature' ? 
                            <span className="very-immature-bullet elo-bullet">&nbsp;</span> : (
                              immatureClass(row.match_count) === 'immature' &&
                              <span className="immature-bullet elo-bullet">&nbsp;</span>
                            )
                        }
                      </td>
                      <td className={classNames("cell-no-padding", {"has-cursor-pointer": row.registrations && row.registrations.length > 0})} data-tooltip-id={row.registrations && row.registrations.length > 0 ? `elo-registration-tooltip-${index}` : undefined}>
                        {row.registrations && row.registrations.length > 0 && (
                          <span className={classNames("icon is-small elo-registration-icon", {
                            "elo-registration-one-week": new Date(row.registrations[0].event_start_date).getTime() - (7 * 24 * 60 * 60 * 1000) < new Date().getTime(),
                            "elo-registration-two-weeks": new Date(row.registrations[0].event_start_date).getTime() - (14 * 24 * 60 * 60 * 1000) < new Date().getTime(),
                            "elo-registration-grey": changed,
                          })}>
                            <i className="fas fa-exclamation-circle"></i>
                          </span>
                        )}
                        {row.registrations && row.registrations.length > 0 && (
                          <Tooltip id={`elo-registration-tooltip-${index}`} className="tooltip-wide" clickable place="left">
                            <div className="elo-registration-tooltip">
                              This athlete is registered for the following upcoming events:
                              <ul>
                                {row.registrations.map((r, index) => (
                                  <li key={index}>
                                    <a href="#" onClick={e => onRegistrationClicked(e, r)}>
                                      {r.event_name} ({formatEventDates(r.event_start_date, r.event_end_date)})
                                      <br />
                                      {r.division}
                                    </a>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          </Tooltip>
                        )}
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
      <Tooltip id="elo-tooltip" className="tooltip-multiline" place="left" />
    </div>
  )
}

export default EloTable