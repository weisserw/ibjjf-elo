import { useState, useEffect } from 'react'
import axios, { AxiosResponse } from 'axios';
import classNames from 'classnames';
import dayjs from 'dayjs';
import DBFilters, { FilterValues } from './DBFilters';
import DBPagination from './DBPagination';
import "./DBTable.css"

interface Row {
  id: string
  winner: string
  winnerStartRating: number
  winnerEndRating: number
  loser: string
  loserStartRating: number
  loserEndRating: number
  event: string
  division: string
  date: string
  notes: string
}

interface Results {
  rows: Row[]
  totalPages: number
}

interface EloTableProps {
  gi: boolean
}

function DBTable(props: EloTableProps) {
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState<Row[]>([])
  const [page, setPage] = useState(1)
  const [totalPages, setTotalPages] = useState(1)
  const [filters, setFilters] = useState<FilterValues>({});

  useEffect(() => {
    axios.get<Results>('/api/matches', {
      params: {
        gi: props.gi ? 'true' : 'false',
        ...filters,
        page: page
      }
    }).then((response: AxiosResponse<Results>) => {
      setData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setLoading(false)

      if (response.data.rows.length === 0 && page > 1) {
        setPage(page - 1)
      }
    }).catch((exception) => {
      console.error(exception)
      setLoading(false)
    })
  }, [props.gi, filters, page]);

  const shortEvent = (row: Row) => {
    if (row.event.length > 32) {
      return row.event.substring(0, 32) + '...'
    }
    return row.event
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

  const outcomeClass = (startRating: number, endRating: number) => {
    if (endRating > startRating) {
      return 'has-text-success'
    } else if (endRating < startRating) {
      return 'has-text-danger'
    } else {
      return ''
    }
  }

  return (
    <div>
      <DBFilters filters={filters} setFilters={setFilters} />
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
              !loading && !!data.length && data.map((row: Row) => (
                <tr key={row.id}>
                  <td>{row.winner}</td>
                  <td>{row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span></td>
                  <td>{row.loser}</td>
                  <td>{row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span></td>
                  <td className="has-tooltip-multiline" data-tooltip={row.event}>
                    {shortEvent(row)}
                  </td>
                  <td>{row.division}</td>
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
          !loading && !!data.length && data.map((row: Row) => (
            <div key={row.id} className="card db-row-card">
              <div className="date-box">
                {dayjs(row.date).format('MMM D YYYY, h:mma')}
              </div>
              <div className="card-content">
                <div className="columns">
                  <div className="column">
                    <strong>Winner:</strong> {row.winner} {row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>
                  </div>
                  <div className="column">
                    <strong>Loser:</strong> {row.loser} {row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>
                  </div>
                </div>
                <div className="columns">
                  <div className="column">
                    {row.event}
                  </div>
                  <div className="column has-text-right-tablet">
                    {row.division}
                  </div>
                </div>
                {row.notes &&
                  <p>{row.notes}</p>
                }
              </div>
            </div>
          ))
        }
      </div>
      {
        !loading && data.length > 0 && (
          <DBPagination page={page} totalPages={totalPages} onNextPage={onNextPage} onPreviousPage={onPreviousPage} onPageClick={onPageClick} />
        )
      }
    </div>
  )
}

export default DBTable;