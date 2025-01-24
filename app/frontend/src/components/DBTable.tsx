import { useState, useEffect, useMemo } from 'react'
import axios, { AxiosResponse } from 'axios';
import classNames from 'classnames';
import dayjs from 'dayjs';
import DBFilters, {
  FilterValues,
  ageToFilter,
  genderToFilter,
  beltToFilter,
  weightToFilter,
  type FilterKeys,
  type OpenFilters
} from './DBFilters';
import DBPagination from './DBPagination';
import "./DBTable.css"

interface Row {
  id: string
  winner: string
  winnerStartRating: number
  winnerEndRating: number
  winnerWeightForOpen: string | null
  winnerRatingNote: string | null
  loser: string
  loserStartRating: number
  loserEndRating: number
  loserWeightForOpen: string | null
  loserRatingNote: string | null
  event: string
  age: string
  gender: string
  belt: string
  weight: string
  date: string
  rated: boolean
  notes: string
}

interface Results {
  rows: Row[]
  totalPages: number
}

interface EloTableProps {
  gi: boolean
  filters: FilterValues
  page: number
  setFilters: (filters: FilterValues) => void
  openFilters: OpenFilters
  setOpenFilters: (openFilters: OpenFilters) => void
  setPage: (page: number) => void
}

function DBTable(props: EloTableProps) {
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [data, setData] = useState<Row[]>([])
  const [totalPages, setTotalPages] = useState(1)

  useEffect(() => {
    setReloading(true)
    axios.get<Results>('/api/matches', {
      params: {
        gi: props.gi ? 'true' : 'false',
        ...props.filters,
        page: props.page
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
  }, [props.gi, props.filters, props.page]);

  const shortEvent = (row: Row) => {
    if (row.event.length > 32) {
      return row.event.substring(0, 32) + '...'
    }
    return row.event
  }

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

  const outcomeClass = (startRating: number, endRating: number) => {
    if (endRating > startRating) {
      return 'has-text-success'
    } else if (endRating < startRating) {
      return 'has-text-danger'
    } else {
      return ''
    }
  }

  const athleteClicked = (event: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    event.preventDefault()
    props.setFilters({
      athlete_name: name,
    });
    props.setOpenFilters({athlete: true, event: false, division: false});
  }

  const eventClicked = (event: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    event.preventDefault()
    const newFilters = {...props.filters};
    delete newFilters.athlete_name;
    newFilters.event_name = name;
    props.setFilters(newFilters);
    props.setOpenFilters({...props.openFilters, event: true});
  }

  const divisionClicked = (event: React.MouseEvent<HTMLAnchorElement>, row: Row) => {
    event.preventDefault()
    const newFilters = {...props.filters};
    delete newFilters.athlete_name;
    const keys: FilterKeys[] = Object.keys(newFilters) as FilterKeys[];
    for (const key of keys.filter(key => key.startsWith('age_') || key.startsWith('gender_') || key.startsWith('belt_') || key.startsWith('weight_'))) {
      delete newFilters[key];
    }
    newFilters[ageToFilter(row.age)] = true;
    newFilters[genderToFilter(row.gender)] = true;
    newFilters[beltToFilter(row.belt)] = true;
    newFilters[weightToFilter(row.weight)] = true;

    props.setFilters(newFilters);
    props.setOpenFilters({...props.openFilters, division: true});
  }

  const openWeightHintText = (row: Row) => {
    if (row.weight.startsWith('Open Class')) {
      return `Weight classes: ${row.winnerWeightForOpen ?? 'Unknown'} vs ${row.loserWeightForOpen  ?? 'Unknown'}`
    } else {
      return undefined
    }
  }

  const weightWithTooltip = (row: Row, bottom: boolean) => {
    const hintText = openWeightHintText(row);
    if (hintText) {
      return (
        <span className={classNames("has-tooltip-multiline", {"has-tooltip-bottom": bottom})} data-tooltip={hintText}>
          {row.weight}
        </span>
      )
    } else {
      return row.weight
    }
  }

  const ratingAsterisk = (note: string | null, bottom: boolean) => {
    if (note) {
      return (
        <span className={classNames("has-tooltip-multiline", {"has-tooltip-bottom": bottom})} data-tooltip={note}>
          <strong>*</strong>
        </span>
      )
    } else {
      return ''
    }
  }

  const isHistorical = (row: Row) => {
    return /\([^\)]+\)/.test(row.event);
  }

  const hasHistorical = useMemo(() => data.some(isHistorical), [data]);

  return (
    <div>
      <DBFilters gi={props.gi}
                 filters={props.filters}
                 setFilters={props.setFilters}
                 openFilters={props.openFilters}
                 setOpenFilters={props.setOpenFilters} />
      <div className="table-container is-hidden-touch">
        <table className={classNames("table db-table is-striped", {"is-narrow": !loading && !!data.length})}>
          <thead>
            <tr>
              <th>Winner</th>
              <th>Rating</th>
              <th>Loser</th>
              <th>Rating</th>
              <th>Event</th>
              <th>Division</th>
              <th>Date</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {
              loading && (
                <tr>
                  <td colSpan={8} className="empty-row">
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
                  <td colSpan={8} className="empty-row">
                    <div className="columns is-centered">
                      No data found
                    </div>
                  </td>
                </tr>
              )
            }
            {
              !loading && !!data.length && data.map((row: Row, index: number) => (
                <tr key={row.id} className={classNames({"is-historical": isHistorical(row)})}>
                  <td><a href="#" onClick={e => athleteClicked(e, row.winner)}>{row.winner}</a></td>
                  <td>{row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>{ratingAsterisk(row.winnerRatingNote, index === 0)}</td>
                  <td><a href="#" onClick={e => athleteClicked(e, row.loser)}>{row.loser}</a></td>
                  <td>{row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>{ratingAsterisk(row.loserRatingNote, index === 0)}</td>
                  <td className={classNames("has-tooltip-multiline", {"has-tooltip-bottom": index === 0})} data-tooltip={shortEvent(row) !== row.event ? row.event : undefined}>
                    <a href="#" onClick={e => eventClicked(e, row.event)}>{shortEvent(row)}</a>
                  </td>
                  <td>
                    <a href="#" onClick={e => divisionClicked(e, row)}>{row.age} / {row.gender} / {row.belt} / {weightWithTooltip(row, index === 0)}</a>
                  </td>
                  <td>{dayjs(row.date).format('MMM D YYYY, h:mma')}</td>
                  <td>{row.notes}</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
      <div className="cards-container is-hidden-desktop">
        {
          loading && (
            <div className="card db-row-card">
              <div className="card-content">
                <div className="columns is-centered">
                  <div className="column is-narrow">
                    <div className="loader"></div>
                  </div>
                </div>
              </div>
            </div>
          )
        }
        {
          !loading && data.length === 0 && (
            <div className="card db-row-card">
              <div className="card-content">
                <div className="columns is-centered">
                  <div className="column is-narrow">
                    No data found
                  </div>
                </div>
              </div>
            </div>
          )
        }
        {
          !loading && !!data.length && data.map((row: Row) => {
            const weightHintText = openWeightHintText(row);
            return (
              <div key={row.id} className={classNames("card db-row-card", {"is-historical": isHistorical(row)})}>
                <div className="date-box">
                  {dayjs(row.date).format('MMM D YYYY, h:mma')}
                </div>
                <div className="card-content">
                  <div className="columns">
                    <div className="column">
                      <strong>Winner:</strong> <a href="#" onClick={e => athleteClicked(e, row.winner)}>{row.winner}</a> {row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>{ratingAsterisk(row.winnerRatingNote, true)}
                    </div>
                    <div className="column has-text-right-tablet">
                      <strong>Loser:</strong> <a href="#" onClick={e => athleteClicked(e, row.loser)}>{row.loser}</a> {row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>{ratingAsterisk(row.loserRatingNote, true)}
                    </div>
                  </div>
                  <div className="columns">
                    <div className="column">
                      <a href="#" onClick={e => eventClicked(e, row.event)}>{row.event}</a>
                    </div>
                    <div className="column has-text-right-tablet">
                      <a href="#" onClick={e => divisionClicked(e, row)}>{row.age} / {row.gender} / {row.belt} / {row.weight}</a>
                    </div>
                  </div>
                  {(weightHintText || row.notes) &&
                    <div className="columns">
                      <div className="column">
                        {weightHintText &&
                          <p>{weightHintText}</p>
                        }
                        {row.notes &&
                          <p>{row.notes}</p>
                        }
                      </div>
                    </div>
                  }
                </div>
              </div>
              );
            }
          )
        }
      </div>
      {
        !loading && data.length > 0 && (
          <DBPagination loading={reloading} page={props.page} totalPages={totalPages} onNextPage={onNextPage} onPreviousPage={onPreviousPage} onPageClick={onPageClick} />
        )
      }
      {
        hasHistorical && (
          <div className="notification is-historical">
            <strong>Historical data (highlighted rows) may be incomplete or inaccurate</strong>
          </div>
        )
      }
    </div>
  )
}

export default DBTable;