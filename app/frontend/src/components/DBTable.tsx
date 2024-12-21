import { useState, useEffect } from 'react'
import axios, { AxiosResponse } from 'axios';
import classNames from 'classnames';
import dayjs from 'dayjs';
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

  useEffect(() => {
    axios.get<Results>('/api/matches', {
      params: {
        gi: props.gi ? 'true' : 'false',
        page: page
      }
    }).then((response: AxiosResponse<Results>) => {
      setData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setLoading(false)
    }).catch((exception) => {
      console.error(exception)
      setLoading(false)
    })
  }, [props.gi, page]);

  const shortEvent = (row: Row) => {
    if (row.event.length > 32) {
      return row.event.substring(0, 32) + '...'
    }
    return row.event
  }

  const onNextPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    setPage(page + 1)
  }

  const onPreviousPage = (event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault()
    setPage(page - 1)
  }

  return (
    <div>
      <div className="table-container">
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
                  <td>{row.winnerStartRating} → {row.winnerEndRating}</td>
                  <td>{row.loser}</td>
                  <td>{row.loserStartRating} → {row.loserEndRating}</td>
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
        <nav className="pagination pagination-margin" role="navigation">
          {
            page > 1 &&
            <a href="#" className="pagination-previous" onClick={onPreviousPage}>Previous</a>
          }
          {
            page < totalPages &&
            <a href="#" className="pagination-next" onClick={onNextPage}>Next</a>
          }
          <ul className="pagination-list">
            <li>
              <a href="#" className="pagination-link">1</a>
            </li>
            <li>
              <span className="pagination-ellipsis">&hellip;</span>
            </li>
            <li>
              <a href="#" className="pagination-link">45</a>
            </li>
            <li>
              <a
                className="pagination-link is-current"
                aria-label="Page 46"
                aria-current="page"
                >46</a>
            </li>
            <li>
              <a href="#" className="pagination-link" >47</a>
            </li>
            <li>
              <span className="pagination-ellipsis">&hellip;</span>
            </li>
            <li>
              <a href="#" className="pagination-link">86</a>
            </li>
          </ul>
        </nav>
      </div>
    </div>
  )
}

export default DBTable;