import { useState, useEffect, useMemo } from 'react'
import axios, { AxiosResponse } from 'axios';
import DBFilters, {
  ageToFilter,
  genderToFilter,
  beltToFilter,
  weightToFilter,
  type FilterKeys
} from './DBFilters';
import DBPagination from './DBPagination';
import DBTableRows from './DBTableRows';
import { useAppContext } from '../AppContext';
import { axiosErrorToast, isHistorical, type DBRow as Row, type DBResults as Results } from '../utils';
import { useNavigate } from 'react-router-dom';
import { t } from '../translate';

import "./DBTable.css"

function DBTable() {
  const [loading, setLoading] = useState(true)
  const [reloading, setReloading] = useState(false)
  const [data, setData] = useState<Row[]>([])
  const [totalPages, setTotalPages] = useState(1)

  const {
    activeTab,
    filters,
    setFilters,
    openFilters,
    setOpenFilters,
    dbPage: page,
    setDbPage: setPage,
    setBracketActiveTab,
    setBracketArchiveEventName,
    setBracketArchiveEventNameFetch,
    setBracketArchiveSelectedCategory,
  } = useAppContext();

  const navigate = useNavigate()

  const gi = activeTab === 'Gi'

  useEffect(() => {
    setReloading(true)
    axios.get<Results>('/api/matches', {
      params: {
        gi: gi ? 'true' : 'false',
        ...filters,
        page: page
      }
    }).then((response: AxiosResponse<Results>) => {
      setData(response.data.rows)
      setTotalPages(response.data.totalPages)
      setLoading(false)
      setReloading(false)

      if (response.data.rows.length === 0) {
        setPage(1)
      }
    }).catch((exception) => {
      axiosErrorToast(exception)
      setLoading(false)
      setReloading(false)
    })
  }, [gi, filters, page]);

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

    navigate(`/athlete/${encodeURIComponent(id)}`)
  }

  const eventClicked = (event: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    event.preventDefault()
    const newFilters = {...filters};
    delete newFilters.athlete_name;
    newFilters.event_name = '"' + name + '"';
    setFilters(newFilters);
    setOpenFilters({...openFilters, event: true});
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
  }

  const divisionBracketClicked = (row: Row) => {
    setBracketActiveTab('Archive')
    setBracketArchiveEventName(row.event)
    setBracketArchiveEventNameFetch(row.event)
    setBracketArchiveSelectedCategory(`${row.belt} / ${row.age} / ${row.gender} / ${row.weight}`)
    navigate('/tournaments')
  }

  const hasHistorical = useMemo(() => data.map(row => row.event).some(isHistorical), [data]);

  if (loading) {
    return (
      <div>
        <DBFilters />
        <div className="table-loader">
          <div className="loader"></div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <DBFilters />
      <DBTableRows data={data}
                   loading={loading}
                   linkAthlete={() => true}
                   athleteClicked={athleteClicked}
                   eventClicked={eventClicked}
                   divisionClicked={divisionClicked}
                   divisionBracketClicked={divisionBracketClicked} />
      {
        data.length > 0 && (
          <DBPagination loading={reloading}
                        page={page}
                        showPages={false}
                        totalPages={totalPages}
                        onFirstPage={onFirstPage}
                        onNextPage={onNextPage}
                        onPreviousPage={onPreviousPage}
                        onPageClick={onPageClick} />
        )
      }
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

export default DBTable;