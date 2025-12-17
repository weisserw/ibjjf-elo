import {useEffect, useState, useMemo, useCallback} from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer } from 'recharts';
import { useParams } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { axiosErrorToast, getCountryName,
  type Registration, type DBRow as Row, type DBResults as Results,
  isHistorical, badgeForPercentile, percentileInteger, formatEventDates } from '../utils';
import GiTabs from './GiTabs';
import { useAppContext } from '../AppContext';
import igLogoColor from '/src/assets/instagram-color.png';
import usadaLogo from '/src/assets/usada.png';
import uaeNadaLogo from '/src/assets/uae-nada.png';
import noPhoto from '/src/assets/no-photo.jpg';
import bjjheroesLogo from '/src/assets/bjjheroes.png';
import { Tooltip } from 'react-tooltip';
import DBTableRows from './DBTableRows';
import { useNavigate } from 'react-router-dom'
import { t, translateMulti, type translationKeys } from '../translate'
import DBPagination from './DBPagination';
import classNames from 'classnames';
import dayjs from 'dayjs';
import {
  ageToFilter,
  genderToFilter,
  beltToFilter,
  weightToFilter,
  type FilterKeys
} from './DBFilters';

import './Athlete.css';

interface Athlete {
  id: string;
  name: string;
  instagram_profile: string | null;
  country: string | null;
  country_note: string | null;
  country_note_pt: string | null;
  personal_name: string | null;
  nickname_translation: string | null;
  bjjheroes_link: string | null;
  instagram_profile_photo_url: string | null;
  team_name: string | null;
  rating: number | null;
  belt: string | null;
}

interface Elo {
  date: string;
  belt: string;
  age: string;
  Rating: number | null;
}

interface Rank {
  rank: number;
  percentile: number;
  age: string;
  belt: string;
  weight: string;
  gender: string;
  avg_rating: number;
}

interface Medal {
  place: number;
  event_name: string;
  event_medals_only: boolean;
  division: string;
  happened_at: string;
}

interface Suspension {
  start_date: string;
  end_date: string;
  reason: string;
  suspending_org: string;
}

interface ResponseData {
  athlete: Athlete;
  eloHistory: Elo[];
  ranks: Rank[];
  registrations: Registration[];
  medals: Medal[];
  suspensions: Suspension[];
}

const ageOrder = (age: string): number => {
  if (age.startsWith('Teen ')) return 0;
  if (age.startsWith('Juvenile ')) return 1;
  if (age === 'Adult') return 2;
  return 3;
}

const ageOrderForMedals = (age: string): number => {
  if (age === 'Teen 1') return 4;
  if (age === 'Teen 2') return 3;
  if (age === 'Teen 3') return 2;
  if (age.startsWith('Juvenile ')) return 1;
  if (age === 'Adult') return 0;
  return 5;
}

const weightOrder: Record<string, number> = {
  '': -1, // P4P
  'Rooster': 0,
  'Light Feather': 1,
  'Feather': 2,
  'Light': 3,
  'Middle': 4,
  'Medium Heavy': 5,
  'Heavy': 6,
  'Super Heavy': 7,
  'Ultra Heavy': 8,
  'Open Class': 9,
  'Open Class Light': 10,
  'Open Class Heavy': 11,
};

const beltNames: Record<string, string> = {
  BLACK: "Black",
  BROWN: "Brown",
  PURPLE: "Purple",
  BLUE: "Blue",
  GREEN: "Green",
  GREEN_ORANGE: "Green-Orange",
  ORANGE: "Orange",
  YELLOW: "Yellow",
  YELLOW_GREY: "Yellow-Grey",
  GREY: "Grey",
  WHITE: "White",
};

const beltColors: Record<string, string> = {
  BLACK: "#000000",
  BROWN: "#a1551eff",
  PURPLE: "#af20afff",
  BLUE: "#1461deff",
  GREEN: "#008000",
  GREEN_ORANGE: "#008000",
  ORANGE: "#FFA500",
  YELLOW: "#FFFF00",
  YELLOW_GREY: "#FFFF00",
  GREY: "#808080",
  WHITE: "#FFFFFF",
};

const beltColorEmojis: Record<string, string> = {
  BLACK: "⚫",
  BROWN: "🟤",
  PURPLE: "🟣",
  BLUE: "🔵",
  GREEN: "🟢",
  GREEN_ORANGE: "🟢",
  ORANGE: "🟠",
  YELLOW: "🟡",
  YELLOW_GREY: "🟡",
  GREY: "⚪",
  WHITE: "⚪",
};

const beltHasOutline: Record<string, boolean> = {
  WHITE: true,
  YELLOW: true,
  YELLOW_GREY: true,
  GREY: true,
  ORANGE: true,
};

const beltOrder = [
  'WHITE',
  'GREY',
  'YELLOW-GREY',
  'YELLOW',
  'ORANGE',
  'GREEN-ORANGE',
  'GREEN',
  'BLUE',
  'PURPLE',
  'BROWN',
  'BLACK',
];

function Athlete() {
	const { id } = useParams();
  const [responseData, setResponseData] = useState<ResponseData | null>(null);
  const [matchData, setMatchData] = useState<Row[]>([]);
  const [loading, setLoading] = useState(false);
  const [reloading, setReloading] = useState(false)
  const [totalPages, setTotalPages] = useState(1)

  const {
    activeTab,
    language,
    medalCaseOpen,
    setMedalCaseOpen,
    setBracketArchiveEventName,
    setBracketArchiveEventNameFetch,
    setBracketArchiveSelectedCategory,
    setBracketSelectedEvent,
    setBracketSelectedCategory,
    setBracketRegistrationSelectedUpcomingLink,
    setBracketRegistrationSelectedCategory,
    athletePage: page,
    setAthletePage: setPage,
    filters,
    setFilters,
    openFilters,
    setOpenFilters,
    setRankingGender,
    setRankingAge,
    setRankingBelt,
    setRankingWeight,
  } = useAppContext();

  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      try {
        const response = await axios.get(`/api/athlete/${id}?gi=${activeTab === 'Gi' ? 'true' : 'false'}`);
        setResponseData(response.data);
        setPage(1);
      } catch (error) {
        axiosErrorToast(error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [id, activeTab]);

  useEffect(() => {
    if (!responseData) return;

    setReloading(true)
    axios.get<Results>('/api/matches', {
      params: {
        gi: activeTab === 'Gi' ? 'true' : 'false',
        athlete_id: responseData.athlete.id,
        page: page
      }
    }).then((response: AxiosResponse<Results>) => {
      setMatchData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setReloading(false)
    }).catch((exception) => {
      axiosErrorToast(exception)
      setReloading(false)
    });
  }, [responseData, activeTab, page]);

  const parsedEloHistory = useMemo(() => {
    if (!responseData) return [];

    return responseData.eloHistory.map(entry => ({
      ...entry,
      date: new Date(entry.date),
    }));
  }, [responseData]);

  const divisionBracketClicked = (row: Row) => {
    setBracketArchiveEventName('"' + row.event + '"')
    setBracketArchiveEventNameFetch('"' + row.event + '"')
    setBracketArchiveSelectedCategory(`${row.belt} / ${row.age} / ${row.gender} / ${row.weight}`)
    navigate('/tournaments/archive')
  }

  const medalBracketClicked = (event: React.MouseEvent<HTMLAnchorElement>, medal: Medal) => {
    event.preventDefault()

    setBracketArchiveEventName('"' + medal.event_name + '"')
    setBracketArchiveEventNameFetch('"' + medal.event_name + '"')
    setBracketArchiveSelectedCategory(medal.division)
    navigate('/tournaments/archive')
  }

  const isWorlds = (eventName: string) => {
    return eventName.toLowerCase().includes("world ");
  }

  const isMajor = (eventName: string) => {
    return [
        "crown ",
        "european ibjjf ",
        "european jiu-jitsu ",
        "pan jiu-jitsu ",
        "pan ibjjf ",
        "pan kids ",
        "campeonato brasileiro ",
      ].some(major => eventName.toLowerCase().includes(major));
  }

  const hasHistorical = useMemo(() => matchData.map(row => row.event).some(isHistorical), [matchData]);

  const hasRating = useMemo(() => {
    if (!responseData) return false;
    return responseData.eloHistory.some(entry => entry.Rating !== null && entry.Rating > 0);
  }, [responseData]);

  const sortedRanks = useMemo(() => {
    if (!responseData) return [];
    
    return [...responseData.ranks].sort((a, b) => {
      if (a.rank !== b.rank) {
        return a.rank - b.rank;
      }
      if (a.age !== b.age) {
        return ageOrder(a.age) - ageOrder(b.age);
      }
      if (a.weight !== b.weight) {
        return (weightOrder[a.weight] ?? 0) - (weightOrder[b.weight] ?? 0);
      }
      return 0;
    });
  }, [responseData]);

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

  const athleteClicked = (event: React.MouseEvent<HTMLAnchorElement>, slug: string) => {
    event.preventDefault()

    navigate('/athlete/' + encodeURIComponent(slug))
  }

  const eventClicked = (event: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    event.preventDefault()

    const newFilters = {...filters};
    delete newFilters.athlete_name;
    newFilters.event_name = '"' + name + '"';
    setFilters(newFilters);
    setOpenFilters({...openFilters, event: true});

    navigate('/database');
  }

  const divisionClicked = (event: React.MouseEvent<HTMLAnchorElement>, row: Row) => {
    event.preventDefault()

    const newFilters = {...filters};
    delete newFilters.athlete_name;
    const keys: FilterKeys[] = Object.keys(newFilters) as FilterKeys[];
    for (const key of keys.filter(key => key.startsWith('age_') || key.startsWith('gender_') || key.startsWith('belt_') || key.startsWith('weight_'))) {
      delete newFilters[key];
    }
    if (row.age.startsWith('Teen ')) {
      newFilters[ageToFilter('Teen')] = true;
    } else if (row.age.startsWith('Juvenile ')) {
      newFilters[ageToFilter('Juvenile')] = true;
    } else {
      newFilters[ageToFilter(row.age)] = true;
    }
    newFilters[genderToFilter(row.gender)] = true;
    newFilters[beltToFilter(row.belt)] = true;
    newFilters[weightToFilter(row.weight)] = true;

    setFilters(newFilters);
    setOpenFilters({...openFilters, division: true});

    navigate('/database');
  }

  const badgeForRank: (ranks: Rank[]) => [string | null, string] = useCallback((ranks: Rank[]) => {
    if (!responseData || responseData.athlete.rating === null || !responseData.athlete.belt) return [null, ''];

    const lowestPercentile = ranks.reduce((min, rank) => Math.min(min, rank.percentile), 1);

    return badgeForPercentile(lowestPercentile, responseData.athlete.belt);
  }, [responseData]);

  const [badge, badgeDescription] = useMemo(() => {
    return badgeForRank(sortedRanks);
  }, [badgeForRank, sortedRanks]);

  const rankDivisionClicked = (rankEntry: Rank, event: React.MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();

    setRankingGender(rankEntry.gender);
    setRankingAge(rankEntry.age);
    setRankingBelt(rankEntry.belt);
    setRankingWeight(rankEntry.weight);

    navigate('/');
  };


  const onRegistrationClicked = (e: React.MouseEvent, registration: Registration) => {
    e.preventDefault();

    // if event start date is in less than 24 hours, go to live brackets
    const eventStartDate = new Date(registration.event_start_date);
    if (eventStartDate.getTime() - new Date().getTime() < 24 * 60 * 60 * 1000) {
      setBracketSelectedEvent(registration.event_id);
      setBracketSelectedCategory(registration.division);
      navigate('/tournaments');
    } else {
      setBracketRegistrationSelectedUpcomingLink(registration.link);
      setBracketRegistrationSelectedCategory(registration.division);
      navigate('/tournaments/registrations');
    }
  }

  const medalEmoji = (medal: Medal) => {
    const divisionParts = medal.division.split(' / ');
    const belt = divisionParts[0];
    const age = divisionParts[1];

    if ((isWorlds(medal.event_name) || isMajor(medal.event_name)) && belt === 'BLACK' && age === 'Adult') {
      return '⭐';
    }

    return beltColorEmojis[belt];
  }

  const removeParens = (str: string) => {
    return str.replace(/\([^)]*\)$/, '');
  };

  const isSuspended = useMemo(() => {
    if (!responseData) return false;
    const today = new Date();
    return responseData.suspensions.some(suspension => {
      const endDate = new Date(suspension.end_date);
      return today <= endDate;
    });
  }, [responseData]);

  if (!responseData) {
    return <div className="loader"></div>;
  }

  const athlete = responseData.athlete;

  const sortedMedals = responseData.medals.sort((a, b) => {
    const aDivisionParts = a.division.split(' / ');
    const bDivisionParts = b.division.split(' / ');

    const aBelt = aDivisionParts[0];
    const bBelt = bDivisionParts[0];

    if (aBelt !== bBelt) {
      return beltOrder.indexOf(bBelt) - beltOrder.indexOf(aBelt);
    }
  
    const aIsWorlds = isWorlds(a.event_name);
    const bIsWorlds = isWorlds(b.event_name);
    if (aIsWorlds !== bIsWorlds) {
      return bIsWorlds ? 1 : -1;
    }

    const aisMajor = isMajor(a.event_name) ? 1 : 0;
    const bisMajor = isMajor(b.event_name) ? 1 : 0;
    if (aisMajor !== bisMajor) {
      return bisMajor - aisMajor;
    }

    if (a.happened_at !== b.happened_at) {
      return b.happened_at.localeCompare(a.happened_at);
    }

    const aAge = aDivisionParts[1];
    const bAge = bDivisionParts[1];

    if (aAge !== bAge) {
      return ageOrderForMedals(aAge) - ageOrderForMedals(bAge);
    }

    if (a.place !== b.place) {
      return a.place - b.place;
    }

    const aWeight = aDivisionParts[2];
    const bWeight = bDivisionParts[2];

    return (weightOrder[aWeight] ?? 0) - (weightOrder[bWeight] ?? 0);
  });

  return (
    <div className="container athlete-container">
      <div className="box athlete-profile-box">
        {athlete.instagram_profile && athlete.instagram_profile_photo_url ? (
          <figure className="image is-128x128" style={{ margin: 0 }}>
            <img
              className="is-rounded athlete-profile-photo"
              src={athlete.instagram_profile_photo_url}
              alt={athlete.instagram_profile}
            />
          </figure>
        ) : (
          <figure className="image is-128x128" style={{ margin: 0 }}>
            <img
              className="is-rounded athlete-profile-photo"
              src={noPhoto}
              alt="No Photo"
            />
          </figure>
        )}
        <div className='athlete-info-box'>
          <Tooltip id='athlete-tooltip' className="tooltip-normal" />
          <h1 className="title is-3 mb-1 athlete-title">
            <span>
              {athlete.personal_name ? athlete.personal_name : athlete.name}
            </span>
            {athlete.country && (
              <span className={`fi fi-${athlete.country.trim().toLowerCase().substring(0, 2)} country-flag`} data-tooltip-place="top" data-tooltip-id='athlete-tooltip' data-tooltip-content={getCountryName(athlete.country, athlete.country_note, athlete.country_note_pt, language)} />
            )}
          </h1>
          {athlete.team_name && (
            <h2 className="subtitle is-5 mt-0 mb-3 athlete-team">
              {athlete.team_name}
            </h2>
          )}
          {
            (athlete.personal_name && athlete.personal_name !== athlete.name) && (
              <h2 className="subtitle is-6 mt-0 mb-3 athlete-fullname">
                <span>{t("Full Name")}: {athlete.name}</span>
              </h2>
            )
          }
          {athlete.nickname_translation && (
            <h2 className="subtitle is-6 mt-0 mb-3 athlete-nickname-translation">
              <span>{t("Nickname Translation")}: "{athlete.nickname_translation}"</span>
            </h2>
          )}
          {athlete.instagram_profile && (
          <h2 className="subtitle is-6 mt-0 mb-2 athlete-nickname">
            <a href={`https://instagram.com/${athlete.instagram_profile}`} target="_blank" rel="noopener noreferrer">
              <img src={igLogoColor} alt="Instagram" className="ig-tooltip-instagram-logo" /> {athlete.instagram_profile}
            </a>
            {
              athlete.bjjheroes_link && (
                <a href={athlete.bjjheroes_link} target="_blank" rel="noopener noreferrer" className="bjjheroes-link">
                  <img src={bjjheroesLogo} alt="BJJ Heroes Profile" />
                </a>
              )
            }
          </h2>
          )}
        </div>
        {!loading &&
        <div className='athlete-rating-box'>
          <div className='athlete-rating-subbox'>
            {(hasRating && athlete.rating !== null) &&
              <h1 className="title mt-0 mb-0 athlete-rating">{athlete.rating}</h1>
            }
            {athlete.belt &&
              <h2
                className={classNames('subtitle mt-0 mb-0 athlete-belt', { 'athlete-belt--outlined': beltHasOutline[athlete.belt] })}
                style={{ color: beltColors[athlete.belt] || 'black' }}
              >
                {t(`${beltNames[athlete.belt]} Belt` as translationKeys)}
              </h2>
            }
            {(badge || activeTab === 'No Gi') && (hasRating && athlete.rating !== null) && (
            <div className='athlete-badge-box'>
              <Tooltip id='athlete-badge-tooltip' className="tooltip-normal" />
              {badge &&
                <figure className="image is-48x48 athlete-elite-badge" style={{ margin: 0 }} data-tooltip-id='athlete-badge-tooltip' data-tooltip-place="top" data-tooltip-content={badgeDescription}>
                  <img
                    src={badge}
                    alt={badgeDescription}
                  />
                </figure>
              }
              {activeTab === 'No Gi' &&
                <div className='white-space-nowrap'>
                  No Gi
                </div>
              }
            </div>
            )}
            {isSuspended && (
              <div className="athlete-suspension-warning">
                {t("Suspended")}
              </div>
            )}
          </div>
        </div>
        }
      </div>
      <GiTabs />
      {
        responseData.suspensions.length > 0 && (
          <div>
            <p className="has-text-weight-bold mb-3">
              {t("Anti-Doping Violations")}:
            </p>
            <table className="table athlete-suspension-table mb-2">
              <thead>
                <tr>
                  <th></th>
                  <th>{t("Start Date")}</th>
                  <th>{t("End Date")}</th>
                  <th>{t("Reason")}</th>
                </tr>
              </thead>
              <tbody>
                {responseData.suspensions.map((suspension, index) => (
                  <tr key={index}>
                    <td>
                      <div className="athlete-suspension-usada-logo-box">
                        {
                        suspension.suspending_org === "USADA" && (
                          <img src={usadaLogo} alt="USADA" className="usada-logo" />
                        )
                        }
                        {
                        suspension.suspending_org === "UAE NADA" && (
                          <img src={uaeNadaLogo} alt="UAE NADA" className="usada-logo" />
                        )
                        }
                      </div>
                    </td>
                    <td>{dayjs(suspension.start_date).format('MMM D, YYYY')}</td>
                    <td>{dayjs(suspension.end_date).format('MMM D, YYYY')}</td>
                    <td>{suspension.reason}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
      <div className="athlete-ranks-upcoming">
        {
          (hasRating && sortedRanks.length > 0) && (
            <div className="athlete-ranks-box">
              <table className="table athlete-ranks-table">
                <thead>
                  <tr>
                    <th>
                      {t("Division")}
                    </th>
                    <th className="has-text-right">
                      <span className="is-hidden-mobile">{t("Average")}</span>
                      <span className="is-visible-mobile">{t("Avg")}</span>
                    </th>
                    <th className="has-text-right">
                      <span className="is-hidden-mobile">{t("Difference")}</span>
                      <span className="is-visible-mobile">{t("Diff")}</span>
                    </th>
                    <th className="has-text-right">
                      {t("Rank")}
                    </th>
                    <th className="has-text-right">
                      <span className="is-hidden-mobile">{t("Percentile")}</span>
                      <span className="is-visible-mobile">{t("Pctl")}</span>
                    </th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {sortedRanks.map((rankEntry, index) => {
                    const [badge, badgeDescription] = badgeForRank([rankEntry]);
                    return (
                    <tr key={index}>
                      <td>
                        <a href="#" onClick={rankDivisionClicked.bind(null, rankEntry)}>
                          {`${t(rankEntry.age as translationKeys)} / ${t((rankEntry.weight || 'P4P') as translationKeys)}`}
                        </a>
                      </td>
                      <td className="has-text-right">
                        {rankEntry.avg_rating !== null ? rankEntry.avg_rating : 'N/A'}
                      </td>
                      <td className="has-text-right">
                        {rankEntry.avg_rating !== null && athlete.rating !== null
                          ? (athlete.rating - rankEntry.avg_rating >= 0 ? '+' : '') + (athlete.rating - rankEntry.avg_rating)
                          : 'N/A'
                        }
                      </td>
                      <td className={classNames('has-text-right', {'has-text-weight-bold': percentileInteger(rankEntry.percentile) >= 90})}>
                        #{rankEntry.rank.toLocaleString()}
                      </td>
                      <td className={classNames('has-text-right', {'has-text-weight-bold': percentileInteger(rankEntry.percentile) >= 90})}>
                          {percentileInteger(rankEntry.percentile)}%
                      </td>
                      <td>
                        {badge &&
                          <Tooltip id={`athlete-rank-badge-tooltip-${index}`} className="tooltip-normal" />
                        }
                        {badge &&
                          <figure className="image is-24x24 athlete-elite-badge" style={{ margin: 0 }} data-tooltip-id={`athlete-rank-badge-tooltip-${index}`} data-tooltip-place="right" data-tooltip-content={badgeDescription}>
                            <img
                              src={badge}
                              alt={badgeDescription}
                            />
                          </figure>
                        }
                      </td>
                    </tr>);
                  })
                }
                </tbody>
              </table>
            </div>
          )
        }
        {
          responseData.registrations.length > 0 && (
            <div className="athlete-registrations-box">
              <h2 className="has-text-weight-bold is-5 mb-2">{t("Upcoming Events")}</h2>
              <div className="athlete-registrations-links">
                {responseData.registrations.map((r, index) => (
                  <div key={index} className="athlete-registration">
                    <a href="#" onClick={e => onRegistrationClicked(e, r)}>
                      <span>{r.event_name}</span>
                      <span className="white-space-nowrap">{formatEventDates(r.event_start_date, r.event_end_date, language)}</span>
                      <span className="white-space-nowrap">{translateMulti(r.division)}</span>
                    </a>
                  </div>))}
              </div>
            </div>
          )
        }
      </div>
      {
        sortedMedals.length > 0 && (
          <div className={classNames("box accordion-box mt-5", {"open": medalCaseOpen})}>
            <div className="accordion">
              <header className="accordion-header" onClick={() => setMedalCaseOpen(!medalCaseOpen)}>
                <p><strong>{t("Earned Medals")} 🏆</strong></p>
                <span className={`accordion-icon ${medalCaseOpen ? 'is-active' : ''}`}>
                  <i className={`fas fa-angle-${medalCaseOpen ? 'up' : 'down'}`}></i>
                </span>
              </header>
              {medalCaseOpen && (
                <div className="accordion-body">
                  <table className="table is-fullwidth medal-case-table">
                    <tbody>
                      {sortedMedals.map((medal, index) => (
                        <tr key={index}>
                          <td className="medal-place-cell cell-no-padding">
                            {medal.place === 1 && '🥇'}
                            {medal.place === 2 && '🥈'}
                            {medal.place === 3 && '🥉'}
                          </td>
                          <td className="medal-event-cell">
                            <div className="medal-event">
                              <span>{medalEmoji(medal)}</span>
                              <span className={classNames({'is-major': isMajor(medal.event_name), 'is-worlds': isWorlds(medal.event_name)})}>{removeParens(medal.event_name)}</span>
                            </div>
                          </td>
                          <td className="medal-division-cell">
                            {(!medal.event_medals_only && !isHistorical(medal.event_name) && !medal.division.includes('Juvenile')) ?
                              <a href="#" onClick={(e) => medalBracketClicked(e, medal)}>
                                {translateMulti(medal.division)}
                              </a> : <span>{translateMulti(medal.division)}</span>
                            }
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </div>
        )
      }
      {
        parsedEloHistory.length === 0 && (
          <div className="notification mt-4">
            {t("No matches found")}
          </div>
        )
      }
      {(hasRating && parsedEloHistory.length > 0) && (
      <div className="box mt-5 athlete-elo-box">
        <h2 className="has-text-weight-bold is-5 mb-2">{t("Rating over time")}</h2>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={parsedEloHistory} margin={{ top: 20, right: 30, left: 0, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e0e0e0" />
            <XAxis
              dataKey="date"
              type="number"
              domain={['dataMin', 'dataMax']}
              scale="time"
              tickFormatter={date => {
                return date.toLocaleString('en-US', { month: 'short', year: 'numeric' });
              }}
              tick={{ fontSize: 13, fill: '#757575' }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis domain={['auto', 'auto']} tick={{ fontSize: 13, fill: '#757575' }} />
            <ChartTooltip
              labelFormatter={date => {
                return date.toLocaleString('en-US', { month: 'short', year: 'numeric' });
              }}
              contentStyle={{ background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8, fontSize: 14 }}
              cursor={false}
              animationDuration={0}
            />
            <Line
              type="linear"
              dataKey="Rating"
              stroke="#797c82"
              strokeWidth={3}
              dot={(props) => {
                const { cx, cy, index } = props;
                const entry = parsedEloHistory[index];
                const belt = entry?.belt;
                const color = beltColors[belt] || '#4285f4';
                const isJuvenile = entry?.age?.startsWith('Juvenile');
                if (isJuvenile) {
                  return (
                    <>
                      <circle
                        cx={cx}
                        cy={cy}
                        r={8}
                        fill="#fff"
                        stroke="black"
                      />
                      <circle
                        cx={cx}
                        cy={cy}
                        r={5}
                        fill={color}
                        stroke={beltHasOutline[belt] ? 'black' : color}
                        strokeWidth={2}
                      />
                    </>
                  );
                }
                return (
                  <circle
                    cx={cx}
                    cy={cy}
                    r={5}
                    fill={color}
                    stroke={beltHasOutline[belt] ? 'black' : color}
                    strokeWidth={2}
                  />
                );
              }}
              activeDot={{ r: 7 }}
              animationDuration={200}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      )}
      {
        matchData && matchData.length > 0 && (
          <div>
            <p className="has-text-weight-bold mb-3">
              {t("Match history")}:
            </p>
            <DBTableRows data={matchData}
                         loading={false}
                         linkAthlete={name => name !== athlete.name }
                         athleteClicked={athleteClicked}
                         eventClicked={eventClicked}
                         divisionClicked={divisionClicked}
                         divisionBracketClicked={divisionBracketClicked}/>
            {
              hasHistorical && (
                <div className="notification is-historical">
                  {t("Match data before December 2024 may be incomplete or inaccurate")}
                </div>
              )
            }
          </div>
        )
      }
      {
        matchData.length > 0 && (
          <div className="mt-4">
            <DBPagination loading={reloading}
                          page={page}
                          showPages={false}
                          totalPages={totalPages}
                          onFirstPage={onFirstPage}
                          onNextPage={onNextPage}
                          onPreviousPage={onPreviousPage}
                          onPageClick={onPageClick} />
          </div>
        )
      }
    </div>
  );
}

export default Athlete;
