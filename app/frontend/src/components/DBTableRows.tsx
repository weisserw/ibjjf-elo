import React from 'react';
import classNames from "classnames";
import dayjs from "dayjs";
import 'dayjs/locale/pt';
import { Tooltip } from 'react-tooltip';
import { isHistorical, noMatchStrings, type DBRow as Row } from "../utils";
import { useAppContext } from '../AppContext';
import { t, translateMulti, translateMultiSpace, translationKeys } from '../translate';
import NameInfo from './NameInfo';

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
  linkAthlete: (name: string) => boolean
  noLinks?: boolean
  athleteClicked?: (e: React.MouseEvent<HTMLAnchorElement>, slug: string) => void
  eventClicked?: (e: React.MouseEvent<HTMLAnchorElement>, name: string) => void
  divisionClicked?: (e: React.MouseEvent<HTMLAnchorElement>, row: Row) => void
  divisionBracketClicked: (row: Row) => void
}

function DBTableRows(props: DBTableRowsProps) {
  const { data, loading, athleteClicked, eventClicked, divisionClicked, divisionBracketClicked, noLinks, linkAthlete } = props;

  const { language } = useAppContext();

  const notesWithWeight = (row: Row) => {
    const weightText = openWeightText(row);
    if (row.notes && weightText) {
      return <span>{weightText}, {translateMulti(row.notes)}</span>
    } else if (weightText) {
      return weightText
    } else {
      return <span>{translateMulti(row.notes)}</span>
    }
  }

  const ratingAsterisk = (note: string | null, bottom: boolean) => {
    if (note) {
      return (
        <span className="has-cursor-pointer" data-tooltip-id={bottom ? "db-bottom-tooltip" : "db-top-tooltip"} data-tooltip-content={translateMulti(note)}>
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
            return <span>{t(row.winnerWeightForOpen as translationKeys)} vs {t(row.loserWeightForOpen as translationKeys)} ({diff} {diff === 1 ? 'class' : 'classes'} {t("apart")}, {t("adjustment")}: <strong className="fw-600">{row.winnerStartRating + handicap}</strong> (+{handicap}) vs {row.loserStartRating}</span>
          } else {
            const diff = loserWeightIndex - winnerWeightIndex;
            const handicap = handicapTable[diff];
            return <span>{t(row.winnerWeightForOpen as translationKeys)} vs {t(row.loserWeightForOpen as translationKeys)} ({diff} {diff === 1 ? 'class' : 'classes'} {t("apart")}, {t("adjustment")}: {row.winnerStartRating} vs <strong className="fw-600">{row.loserStartRating + handicap}</strong> (+{handicap})</span>
          }
        }
      }
      return <span>{t((row.winnerWeightForOpen ?? "Unknown Weight") as translationKeys)} vs {t((row.loserWeightForOpen  ?? "Unknown Weight") as translationKeys)}, {t("no adjustment")}</span>
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

  const showRating = (row: Row) => {
    return !row.age.startsWith('Teen')
  }

  return (
    <>
      <div className="table-container is-hidden-touch">
        <table className={classNames("table db-table is-striped", {"is-narrow": !loading && !!data.length})}>
          <thead>
            <tr>
              <th>{t("Winner")}</th>
              <th>{t("Rating")}</th>
              <th>{t("Loser")}</th>
              <th>{t("Rating")}</th>
              <th>{t("Tournament")}</th>
              <th>{t("Division")}</th>
              <th>{t("Date / Location")}</th>
              <th>{t("Notes")}</th>
            </tr>
          </thead>
          <tbody>
            {
              data.length === 0 && (
                <tr>
                  <td colSpan={8} className="empty-row">
                    <div className="columns is-centered">
                      {t("No matches found for the selected filters")}
                    </div>
                  </td>
                </tr>
              )
            }
            {
              !!data.length && data.map((row: Row, index: number) => (
                <tr key={row.id} data-id={row.id} className={classNames({"is-historical": isHistorical(row.event)})}>
                  <td data-id={row.winnerId}>
                    {
                      !linkAthlete(row.winner) ? (row.winnerPersonalName ? row.winnerPersonalName : row.winner) :
                      <div className="name-container">
                        <a href="#" onClick={e => athleteClicked?.(e, row.winnerSlug)}>
                          {row.winnerPersonalName ? row.winnerPersonalName : row.winner}
                        </a>
                        <NameInfo instagram_profile={row.winnerInstagramProfile}
                                  profile_image_url={row.winnerProfileImageUrl}
                                  country={row.winnerCountry}
                                  country_note={row.winnerCountryNote}
                                  country_note_pt={row.winnerCountryNotePt} />
                      </div>
                    }
                  </td>
                  <td>
                    {
                    showRating(row) &&
                      <span>
                      {row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>{ratingAsterisk(row.winnerRatingNote, index === 0)}
                      </span>
                    }
                  </td>
                  <td data-id={row.loserId}>
                    {
                      !linkAthlete(row.loser) ? (row.loserPersonalName ? row.loserPersonalName : row.loser) :
                      <div className="name-container">
                        <a href="#" onClick={e => athleteClicked?.(e, row.loserSlug)} className={classNames({"strike-through": noMatchStrings.some(s => row.notes?.toLowerCase() === s)})}>
                          {row.loserPersonalName ? row.loserPersonalName : row.loser}
                        </a>
                        <NameInfo instagram_profile={row.loserInstagramProfile}
                                  profile_image_url={row.loserProfileImageUrl}
                                  country={row.loserCountry}
                                  country_note={row.loserCountryNote}
                                  country_note_pt={row.loserCountryNotePt} />
                      </div>
                    }
                  </td>
                  <td>
                    {
                    showRating(row) &&
                      <span>
                      {row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>{ratingAsterisk(row.loserRatingNote, index === 0)}
                      </span>
                    }
                  </td>
                  <td className="has-cursor-pointer" data-tooltip-id={index === 0 ? "db-bottom-tooltip" : "db-top-tooltip"} data-tooltip-content={shortEvent(row) !== row.event ? row.event : undefined}>
                    {
                      noLinks ? shortEvent(row) :
                      <a href="#" onClick={e => eventClicked?.(e, row.event)}>{shortEvent(row)}</a>
                    }
                  </td>
                  <td>
                    <div className="division-box">
                      {
                        noLinks ? <span>{t(row.age as translationKeys)} / {t(row.gender as translationKeys)} / {t(row.belt as translationKeys)} / {t(row.weight as translationKeys)}</span> :
                        <a href="#" onClick={e => divisionClicked?.(e, row)}>{t(row.age as translationKeys)} / {t(row.gender as translationKeys)} / {t(row.belt as translationKeys)} / {t(row.weight as translationKeys)}</a>
                      }
                      {
                        !isHistorical(row.event) && row.age !== "Juvenile" &&
                        <button className="button is-small is-tiny" onClick={() => divisionBracketClicked?.(row)}>
                          <span className="icon has-text-info">
                            <i className="fas fa-project-diagram"/>
                          </span>
                        </button>
                      }
                    </div>
                  </td>
                  <td>{dayjs(row.date).locale(language).format('MMM D YYYY, h:mma')}{row.matchLocation && ` ${translateMultiSpace(row.matchLocation)}`}</td>
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
                    {t("No matches found for the selected filters")}
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
              <div key={row.id} data-id={row.id} className={classNames("card db-row-card", {"is-historical": isHistorical(row.event)})}>
                <div className="date-box">
                  {dayjs(row.date).locale(language).format('MMM D YYYY, h:mma')}{row.matchLocation && ` ${row.matchLocation}`}
                </div>
                <div className="card-content">
                  <div className="columns">
                    <div className="column" data-id={row.winnerId}>
                      <strong>{t("Winner")}:</strong>{' '}
                      {
                        !linkAthlete(row.winner) ? (row.winnerPersonalName ? row.winnerPersonalName : row.winner) :
                        <div className="name-container">
                          <a href="#" onClick={e => athleteClicked?.(e, row.winnerSlug)}>{row.winnerPersonalName ? row.winnerPersonalName : row.winner}</a>
                          <NameInfo instagram_profile={row.winnerInstagramProfile}
                                    profile_image_url={row.winnerProfileImageUrl}
                                    country={row.winnerCountry}
                                    country_note={row.winnerCountryNote}
                                    country_note_pt={row.winnerCountryNotePt} />
                        </div>
                      }
                      {' '}
                      {
                      showRating(row) &&
                        <span>
                          {row.winnerStartRating} → <span className={outcomeClass(row.winnerStartRating, row.winnerEndRating)}>{row.winnerEndRating}</span>{ratingAsterisk(row.winnerRatingNote, true)}
                        </span>
                      }
                    </div>
                    <div className="column has-text-right-tablet" data-id={row.loserId}>
                      <strong>{t("Loser")}:</strong>{' '}
                      {
                        !linkAthlete(row.loser) ?
                        (row.loserPersonalName ? row.loserPersonalName : row.loser) :
                        <div className="name-container">
                          <a href="#" onClick={e => athleteClicked?.(e, row.loserSlug)} className={classNames({"strike-through": noMatchStrings.some(s => row.notes?.toLowerCase() === s)})}>
                            {row.loserPersonalName ? row.loserPersonalName : row.loser}
                          </a>
                          <NameInfo instagram_profile={row.loserInstagramProfile}
                                    profile_image_url={row.loserProfileImageUrl}
                                    country={row.loserCountry}
                                    country_note={row.loserCountryNote}
                                    country_note_pt={row.loserCountryNotePt} />
                        </div>
                      }
                      {
                      showRating(row) &&
                        <span>
                          {' '}{row.loserStartRating} → <span className={outcomeClass(row.loserStartRating, row.loserEndRating)}>{row.loserEndRating}</span>{ratingAsterisk(row.loserRatingNote, true)}
                        </span>
                      }
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
                          !isHistorical(row.event) &&
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
      <Tooltip id="db-top-tooltip" className="tooltip-multiline" />
      <Tooltip id="db-bottom-tooltip" className="tooltip-multiline" place="bottom"/>
    </>
  )
}

export default DBTableRows
