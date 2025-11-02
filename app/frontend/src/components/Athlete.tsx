import {useEffect, useState, useMemo} from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer } from 'recharts';
import { useParams } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { axiosErrorToast, getCountryName, type DBRow as Row, type DBResults as Results, isHistorical } from '../utils';
import GiTabs from './GiTabs';
import { useAppContext } from '../AppContext';
import igLogoColor from '/src/assets/instagram-color.png';
import eliteDiamondBadge from '/src/assets/elite-diamond.png';
import eliteSapphireBadge from '/src/assets/elite-sapphire.png';
import eliteEmeraldBadge from '/src/assets/elite-emerald.png';
import { Tooltip } from 'react-tooltip';
import DBTableRows from './DBTableRows';
import { useNavigate } from 'react-router-dom'
import { t } from '../translate'
import DBPagination from './DBPagination';
import classNames from 'classnames';
import {
  ageToFilter,
  genderToFilter,
  beltToFilter,
  weightToFilter,
  type FilterKeys
} from './DBFilters';

import './Athlete.css';

interface ResponseData {
  athlete: {
    name: string;
    instagram_profile: string | null;
    country: string | null;
    country_note: string | null;
    country_note_pt: string | null;
    instagram_profile_personal_name: string | null;
    instagram_profile_photo_url: string | null;
    team_name: string | null;
    rating: number | null;
    belt: string;
  };
  eloHistory: {
    date: string;
    Rating: number | null;
  }[];
  ranks: {
    rank: number;
    percentile: number;
    age: string;
    belt: string;
    weight: string;
    avg_rating: number;
  }[];
}

const ageOrder = (age: string): number => {
  if (age.startsWith('Teen ')) return 0;
  if (age.startsWith('Juvenile ')) return 1;
  if (age === 'Adult') return 2;
  return 3;
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
  BROWN: "#8B4513",
  PURPLE: "#800080",
  BLUE: "#0000FF",
  GREEN: "#008000",
  GREEN_ORANGE: "#008000",
  ORANGE: "#FFA500",
  YELLOW: "#FFFF00",
  YELLOW_GREY: "#FFFF00",
  GREY: "#808080",
  WHITE: "#FFFFFF",
};

const beltHasOutline: Record<string, boolean> = {
  WHITE: true,
  YELLOW: true,
  YELLOW_GREY: true,
  GREY: true,
  ORANGE: true,
};

const outlineStyle = {
  textShadow: [
    '-1px -1px 0 black',
     '1px -1px 0 black',
    '-1px  1px 0 black',
     '1px  1px 0 black'
  ].join(', ')
};

const pctInt = (percentile: number): number => {
  return Math.round((1 - percentile) * 100);
}

function Athlete() {
	const { id } = useParams();
  const [responseData, setResponseData] = useState<ResponseData | null>(null);
  const [matchData, setMatchData] = useState<Row[]>([]);
  const [reloading, setReloading] = useState(false)
  const [totalPages, setTotalPages] = useState(1)

  const {
    activeTab,
    language,
    setBracketActiveTab,
    setBracketArchiveEventName,
    setBracketArchiveEventNameFetch,
    setBracketArchiveSelectedCategory,
    athletePage: page,
    setAthletePage: setPage,
    filters,
    setFilters,
    openFilters,
    setOpenFilters,
  } = useAppContext();

  const navigate = useNavigate();

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await axios.get(`/api/athlete/${id}?gi=${activeTab === 'Gi' ? 'true' : 'false'}`);
        setResponseData(response.data);
        setPage(1);
      } catch (error) {
        axiosErrorToast(error);
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
        athlete_name: '"' + responseData.athlete.name + '"',
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
    setBracketActiveTab('Archive')
    setBracketArchiveEventName('"' + row.event + '"')
    setBracketArchiveEventNameFetch('"' + row.event + '"')
    setBracketArchiveSelectedCategory(`${row.belt} / ${row.age} / ${row.gender} / ${row.weight}`)
    navigate('/tournaments')
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

  const athleteClicked = (event: React.MouseEvent<HTMLAnchorElement>, _name: string, id: string) => {
    event.preventDefault()

    navigate('/athlete/' + encodeURIComponent(id))
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

  const [badge, badgeDescription] = useMemo(() => {
    if (!responseData || responseData.athlete.rating === null) return [null, ''];

    if (['WHITE', 'GREY', 'YELLOW', 'YELLOW_GREY', 'ORANGE', 'GREEN', 'GREEN_ORANGE'].includes(responseData.athlete.belt)) {
      return [null, ''];
    }

    const hasAdultBadge = responseData.ranks.some(rank => rank.age === 'Adult' && pctInt(rank.percentile) >= 90);

    const highestPercentile = responseData.ranks.reduce((max, rank) => Math.max(max, pctInt(rank.percentile)), 0);
    if (highestPercentile >= 98 && hasAdultBadge) {
      return [eliteDiamondBadge, 'Elite (Diamond)'];
    } else if (highestPercentile >= 95) {
      return [eliteSapphireBadge, 'Elite (Sapphire)'];
    } else if (highestPercentile >= 90) {
      return [eliteEmeraldBadge, 'Elite (Emerald)'];
    } else {
      return [null, ''];
    }
  }, [responseData]);

  if (!responseData) {
    return <div className="loader"></div>;
  }

  return (
    <div className="container athlete-container">
      <div className="box athlete-profile-box">
        {responseData.athlete.instagram_profile && responseData.athlete.instagram_profile_photo_url && (
          <figure className="image is-128x128" style={{ margin: 0 }}>
            <img
              className="is-rounded athlete-profile-photo"
              src={responseData.athlete.instagram_profile_photo_url}
              alt={responseData.athlete.instagram_profile}
            />
          </figure>
        )}
        <div>
          <Tooltip id='athlete-tooltip' className="tooltip-normal" />
          <h1 className="title is-3 mb-1 athlete-title">
            {responseData.athlete.name}
            {responseData.athlete.country && (
              <span className={`fi fi-${responseData.athlete.country.trim().toLowerCase().substring(0, 2)} country-flag`} data-tooltip-place="top" data-tooltip-id='athlete-tooltip' data-tooltip-content={getCountryName(responseData.athlete.country, responseData.athlete.country_note, responseData.athlete.country_note_pt, language)} />
            )}
          </h1>
          {responseData.athlete.instagram_profile && (
          <h2 className="subtitle is-5 mt-0 mb-2 athlete-nickname">
            <a href={`https://instagram.com/${responseData.athlete.instagram_profile}`} target="_blank" rel="noopener noreferrer">
              <img src={igLogoColor} alt="Instagram" className="ig-tooltip-instagram-logo" />
              {responseData.athlete.instagram_profile_personal_name || `@${responseData.athlete.instagram_profile}`}
            </a>
          </h2>
          )}
          {responseData.athlete.team_name && (
            <h2 className="subtitle is-6 mt-0 mb-2 athlete-team">
              {responseData.athlete.team_name}
            </h2>
          )}
        </div>
        <div className='athlete-rating-box'>
          <div className='athlete-rating-subbox'>
            {(hasRating && responseData.athlete.rating !== null) &&
              <h1 className="title mt-0 mb-0 athlete-rating">{responseData.athlete.rating}</h1>
            }
            <h2 className="subtitle mt-0 mb-0 athlete-belt" style={{color: beltColors[responseData.athlete.belt] || 'black', ...(beltHasOutline[responseData.athlete.belt] ? outlineStyle : {})}}>
              {beltNames[responseData.athlete.belt]} Belt
            </h2>
          </div>
          {(badge || activeTab === 'No Gi') && (
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
                <div className='athlete-no-gi-badge'>
                  No Gi
                </div>
              }
            </div>
          )}
          </div>
      </div>
      <GiTabs />
      {
        (hasRating && sortedRanks.length > 0) && (
          <div className="athlete-ranks-box">
            <table className="table is-striped athlete-ranks-table">
              <thead>
                <tr>
                  <th></th>
                  <th>{t("Rank")}</th>
                  <th>{t("Percentile")}</th>
                </tr>
              </thead>
              <tbody>
                {sortedRanks.map((rankEntry, index) => (
                  <tr key={index}>
                    <td>{`${rankEntry.age} / ${rankEntry.weight || 'P4P'}`}</td>
                    <td className={classNames('has-text-right', {'has-text-weight-bold': pctInt(rankEntry.percentile) >= 90})}>#{rankEntry.rank.toLocaleString()}</td>
                    <td className={classNames('has-text-right', {'has-text-weight-bold': pctInt(rankEntry.percentile) >= 90})}>
                      <Tooltip id={`avg-rating-tooltip-${index}`} className="tooltip-normal" />
                      <span data-tooltip-id={`avg-rating-tooltip-${index}`} data-tooltip-place="top" data-tooltip-content={t("Division Average") + ": " + rankEntry.avg_rating.toString()}>
                        {pctInt(rankEntry.percentile)}%
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }
      {
        parsedEloHistory.length === 0 && (
          <div className="notification">
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
              type="monotone"
              dataKey="Rating"
              stroke="#4285f4"
              strokeWidth={3}
              dot={{ r: 5, fill: '#fff', stroke: '#4285f4', strokeWidth: 2 }}
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
                         linkAthlete={name => name !== responseData.athlete.name }
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
