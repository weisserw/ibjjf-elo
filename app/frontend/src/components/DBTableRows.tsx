import React from 'react';
import classNames from "classnames";
import dayjs from "dayjs";
import { isHistorical, type DBRow as Row } from "../utils";

const BLACK_WEIGHT_HANDICAPS = [
  0,
  54,
  64,
  132,
  169,
  176,
  224,
  373,
  435,
]

const COLOR_WEIGHT_HANDICAPS = [
  0,
  23,
  61,
  74,
  120,
  182,
  224,
  373,
  435,
]

const WEIGHT_CLASSES: Record<string, number> = {
  'Rooster': 0,
  'Light Feather': 1,
  'Feather': 2,
  'Light': 3,
  'Middle': 4,
  'Medium Heavy': 5,
  'Heavy': 6,
  'Super Heavy': 7,
  'Ultra Heavy': 8
}

interface DBTableRowsProps {
  data: Row[]
  loading: boolean
  noLinks?: boolean
  athleteClicked?: (e: React.MouseEvent<HTMLAnchorElement>, name: string) => void
  eventClicked?: (e: React.MouseEvent<HTMLAnchorElement>, name: string) => void
  divisionClicked?: (e: React.MouseEvent<HTMLAnchorElement>, row: Row) => void
  divisionBracketClicked?: (row: Row) => void
}

function DBTableRows(props: DBTableRowsProps) {
  const { data, loading, athleteClicked, eventClicked, divisionClicked, divisionBracketClicked, noLinks } = props;

  const notesWithWeight = (row: Row) => {
    const weightText = openWeightText(row);
    if (row.notes && weightText) {
      return <span>{weightText}, {row.notes}</span>
    } else if (weightText) {
      return weightText
    } else {
      return <span>{row.notes}</span>
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

  const openWeightText = (row: Row): JSX.Element | undefined => {
    if (row.weight.startsWith('Open Class')) {
      if (row.winnerWeightForOpen && row.loserWeightForOpen && WEIGHT_CLASSES[row.winnerWeightForOpen] !== undefined && WEIGHT_CLASSES[row.loserWeightForOpen] !== undefined) {
        const winnerWeightIndex = WEIGHT_CLASSES[row.winnerWeightForOpen];
        const loserWeightIndex = WEIGHT_CLASSES[row.loserWeightForOpen];

        if (winnerWeightIndex !== loserWeightIndex) {
          const handicapTable = row.belt === 'BLACK' ? BLACK_WEIGHT_HANDICAPS : COLOR_WEIGHT_HANDICAPS;
          if (winnerWeightIndex > loserWeightIndex) {
            const diff = winnerWeightIndex - loserWeightIndex;
            const handicap = handicapTable[diff];
            return <span>{row.winnerWeightForOpen} vs {row.loserWeightForOpen} ({diff} {diff === 1 ? 'class' : 'classes'} apart), adjustment: <strong className="fw-600">{row.winnerStartRating + handicap}</strong> (+{handicap}) vs {row.loserStartRating}</span>
          } else {
            const diff = loserWeightIndex - winnerWeightIndex;
            const handicap = handicapTable[diff];
            return <span>{row.winnerWeightForOpen} vs {row.loserWeightForOpen} ({diff} {diff === 1 ? 'class' : 'classes'} apart), adjustment: {row.winnerStartRating} vs <strong className="fw-600">{row.loserStartRating + handicap}</strong> (+{handicap})</span>
          }
        }
      }
      return <span>{row.winnerWeightForOpen ?? 'Unknown Weight'} vs {row.loserWeightForOpen  ?? 'Unknown Weight'}, no adjustment</span>
    } else {
      return undefined
    }
  }

  const outcomeClass = (startRating: number, endRating: number) => {
    if (endRating > startRating) {
      return 'has-text-success'
    } else if (endRating < startRating) {
      return 'has-text-danger'
    } else {
      return '';
    }
  }

  const shortEvent = (row: Row) => {
    if (row.event.length > 32) {
      return row.event.substring(0, 32) + '...'
    }
    return row.event
  }

  return (
    <>
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
              data.length === 0 && (
                <tr>
                  <td colSpan={8} className="empty-row">
                    <div className="columns is-centered">
                      No matches found for the selected filters
                    </div>
                  </td>
                </tr>
              )
            }
            {
              !!data.length && data.map((row: Row, index: number) => (
                <tr key={row.id} data-id={row.id} className={classNames({"is-historical": isHistorical(row)})}>
                  <td data-id={row.winnerId}>
                    {
                      noLinks ? row.winner :
                      <a href="#" onClick={e => athleteClicked?.(e, row.winner)}>{row.winner}</a>
                    }
                  </td>
                  <td>{row.winnerStartRating}→ <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>{ratingAsterisk(row.winnerRatingNote, index === 0)}</td>
                  <td data-id={row.loserId}>
                    {
                      noLinks ? row.loser :
                      <a href="#" onClick={e => athleteClicked?.(e, row.loser)}>{row.loser}</a>
                    }
                  </td>
                  <td>{row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>{ratingAsterisk(row.loserRatingNote, index === 0)}</td>
                  <td className={classNames("has-tooltip-multiline", {"has-tooltip-bottom": index === 0})} data-tooltip={shortEvent(row) !== row.event ? row.event : undefined}>
                    {
                      noLinks ? shortEvent(row) :
                      <a href="#" onClick={e => eventClicked?.(e, row.event)}>{shortEvent(row)}</a>
                    }
                  </td>
                  <td>
                    <div className="division-box">
                      {
                        noLinks ? <span>{row.age} / {row.gender} / {row.belt} / {row.weight}</span> :
                        <a href="#" onClick={e => divisionClicked?.(e, row)}>{row.age} / {row.gender} / {row.belt} / {row.weight}</a>
                      }
                      {
                        (!noLinks && !isHistorical(row)) &&
                        <button className="button is-small is-tiny" onClick={() => divisionBracketClicked?.(row)}>
                          <span className="icon has-text-info">
                            <i className="fas fa-project-diagram"/>
                          </span>
                        </button>
                      }
                    </div>
                  </td>
                  <td>{dayjs(row.date).format('MMM D YYYY, h:mma')}</td>
                  <td>{notesWithWeight(row)}</td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>
      <div className="cards-container is-hidden-desktop">
        {
          data.length === 0 && (
            <div className="card db-row-card">
              <div className="card-content">
                <div className="columns is-centered">
                  <div className="column is-narrow">
                    No matches found for the selected filters
                  </div>
                </div>
              </div>
            </div>
          )
        }
        {
          !!data.length && data.map((row: Row) => {
            const weightText = openWeightText(row);
            return (
              <div key={row.id} className={classNames("card db-row-card", {"is-historical": isHistorical(row)})}>
                <div className="date-box">
                  {dayjs(row.date).format('MMM D YYYY, h:mma')}
                </div>
                <div className="card-content">
                  <div className="columns">
                    <div className="column" data-id={row.winnerId}>
                      <strong>Winner:</strong>{' '}
                      {
                        noLinks ? row.winner :
                        <a href="#" onClick={e => athleteClicked?.(e, row.winner)}>{row.winner}</a>
                      }
                      {' '}{row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>{ratingAsterisk(row.winnerRatingNote, true)}
                    </div>
                    <div className="column has-text-right-tablet" data-id={row.loserId}>
                      <strong>Loser:</strong>{' '}
                      {
                        noLinks ? row.loser :
                        <a href="#" onClick={e => athleteClicked?.(e, row.loser)}>{row.loser}</a>
                      }
                      {' '}{row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>{ratingAsterisk(row.loserRatingNote, true)}
                    </div>
                  </div>
                  <div className="columns">
                    <div className="column">
                      {
                        noLinks ? row.event :
                        <a href="#" onClick={e => eventClicked?.(e, row.event)}>{row.event}</a>
                      }
                    </div>
                    <div className="column has-text-right-tablet">
                      <div className="division-box">
                        {
                          noLinks ? <span>{row.age} / {row.gender} / {row.belt} / {row.weight}</span> :
                          <a href="#" onClick={e => divisionClicked?.(e, row)}>{row.age} / {row.gender} / {row.belt} / {row.weight}</a>
                        }
                        {
                          (!noLinks && !isHistorical(row)) &&
                          <button className="button is-small is-tiny" onClick={() => divisionBracketClicked?.(row)}>
                            <span className="icon has-text-info">
                              <i className="fas fa-project-diagram"/>
                            </span>
                          </button>
                        }
                      </div>
                    </div>
                  </div>
                  {(weightText || row.notes) &&
                    <div className="columns">
                      <div className="column">
                        {weightText &&
                          <p>{weightText}</p>
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
    </>
  )
}

export default DBTableRows
