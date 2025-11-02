import {useEffect, useState, useMemo} from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip as ChartTooltip, ResponsiveContainer } from 'recharts';
import { useParams } from 'react-router-dom';
import axios, { AxiosResponse } from 'axios';
import { axiosErrorToast, getCountryName, type DBRow as Row, type DBResults as Results, isHistorical } from '../utils';
import GiTabs from './GiTabs';
import { useAppContext } from '../AppContext';
import igLogoColor from '/src/assets/instagram-color.png';
import { Tooltip } from 'react-tooltip';
import DBTableRows from './DBTableRows';
import { useNavigate } from 'react-router-dom'
import { t } from '../translate'
import DBPagination from './DBPagination';

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
  };
  eloHistory: {
    date: string;
    Rating: number;
  }[];
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
      </div>
      <GiTabs />
      <div className="box mt-5 athlete-elo-box">
        <h2 className="has-text-weight-bold is-5 mb-2">{t("Rating over time")}</h2>
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={parsedEloHistory} margin={{ top: 20, right: 30, left: 0, bottom: 10 }}>
            <defs>
              <linearGradient id="eloColor" x1="0" y1="0" x2="1" y2="0">
                <stop offset="0%" stopColor="#4285f4" stopOpacity={0.8} />
                <stop offset="100%" stopColor="#34a853" stopOpacity={0.8} />
              </linearGradient>
            </defs>
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
              stroke="url(#eloColor)"
              strokeWidth={3}
              dot={{ r: 5, fill: '#fff', stroke: '#4285f4', strokeWidth: 2 }}
              activeDot={{ r: 7 }}
              animationDuration={200}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      {
        matchData && matchData.length > 0 && (
          <div>
            <p className="has-text-weight-bold mb-3">
              {t("Match history")}:
            </p>
            <DBTableRows data={matchData}
                          loading={false}
                          noLinks={true}
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
