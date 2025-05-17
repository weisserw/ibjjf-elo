import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable from './BracketTable'
import { isGi, handleError, type CompetitorsResponse, type Competitor } from './BracketUtils'

interface RegistrationCategoriesResponse {
  event_name?: string
  total_competitors?: number
  categories?: string[]
  error?: string
}

interface RecentLink {
  name: string
  link: string
}

interface RecentLinksResponse {
  links?: RecentLink[]
}

function BracketRegistration() {
  const [error, setError] = useState<string | null>(null)
  const [recentLinks, setRecentLinks] = useState<RecentLink[]>([])
  const [selectedRecentLink, setSelectedRecentLink] = useState<string>('')
  const [loading, setLoading] = useState(false)


  const {
    bracketRegistrationUrl: registrationUrl,
    setBracketRegistrationUrl: setRegistrationUrl,
    bracketRegistrationEventName: registrationEventName,
    setBracketRegistrationEventName: setRegistrationEventName,
    bracketRegistrationEventTotal: registrationEventTotal,
    setBracketRegistrationEventTotal: setRegistrationEventTotal,
    bracketRegistrationEventUrl: registrationEventUrl,
    setBracketRegistrationEventUrl: setRegistrationEventUrl,
    bracketRegistrationCategories: registrationCategories,
    setBracketRegistrationCategories: setRegistrationCategories,
    bracketRegistrationSelectedCategory: selectedRegistrationCategory,
    setBracketRegistrationSelectedCategory: setSelectedRegistrationCategory,
    bracketRegistrationCompetitors: registrationCompetitors,
    setBracketRegistrationCompetitors: setRegistrationCompetitors,
    setFilters,
    setOpenFilters,
    setActiveTab,
  } = useAppContext()

  const navigate = useNavigate()

  const getRegistrationCompetitors = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<CompetitorsResponse>('/api/brackets/registrations/competitors', {
        params: {
          link: registrationEventUrl,
          division: selectedRegistrationCategory,
          gi: isGi(registrationEventName)
        }
      });
      if (data.error) {
        setRegistrationCompetitors(null)
        setError(data.error)
      } else if (data.competitors) {
        setRegistrationCompetitors(data.competitors)
        setError(null)
      }
    } catch (err) {
      handleError(err, setError)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    if (registrationEventUrl && selectedRegistrationCategory) {
      getRegistrationCompetitors()
    }
  }, [registrationEventUrl, selectedRegistrationCategory])

  useEffect(() => {
    const getRecentLinks = async () => {
      const { data } = await axios.get<RecentLinksResponse>('/api/brackets/registrations/recent');

      if (data.links) {
        setRecentLinks(data.links)
      }
    }
    getRecentLinks()
  }, [])

  const registrationAthleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()
    setFilters({
      athlete_name: '"' + name + '"',
    });
    setOpenFilters({athlete: true, event: false, division: false});
    setActiveTab(isGi(registrationEventName) ? 'Gi' : 'No Gi');
    navigate('/database');
  }

  const sortedRegistrationCompetitors = useMemo(() => {
    if (registrationCompetitors === null) {
      return null
    }
    return [...registrationCompetitors].sort((a, b) => {
      const aRating = a.rating ?? -1;
      const bRating = b.rating ?? -1;
      if (aRating === bRating) {
        return a.name.localeCompare(b.name)
      } else {
        return bRating - aRating
      }
    });
  }, [registrationCompetitors])

  const averageRating = useMemo(() => {
    if (registrationCompetitors === null || registrationCompetitors.length === 0) {
      return undefined
    }
    const ratings = registrationCompetitors.map(c => c.rating).filter(r => r !== undefined && r !== null) as number[]
    if (ratings.length === 0) {
      return undefined
    }
    const sum = ratings.reduce((a, b) => a + b, 0)
    return Math.round(sum / ratings.length)
  }, [registrationCompetitors])

  const onRegistrationUrlKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'Enter' && registrationUrl) {
      getRegistrationCategories(registrationUrl)
    }
  }

  const getRegistrationCategories = async (url: string) => {
    setLoading(true)
    try {
      const { data } = await axios.get<RegistrationCategoriesResponse>('/api/brackets/registrations/categories', {
        params: {
          link: url
        }
      });
      if (data.error) {
        setRegistrationCategories(null)
        setRegistrationEventName('')
        setRegistrationEventTotal(null)
        setRegistrationEventUrl('')
        setError(data.error)
      } else if (data.categories && data.event_name) {
        setError(null)
        setRegistrationEventName(data.event_name)
        setRegistrationEventTotal(data.total_competitors ?? null)
        setRegistrationEventUrl(url)
        setRegistrationCategories(data.categories)

        let selected: string | null | undefined = null

        selected = data.categories.find(c => /(BLACK|PRETA) \/ (Adult|Adulto) \/ (Male|Masculino) \/ (Heavy|Pesado)/.test(c))

        // otherwise use the first adult black category
        if (!selected) {
          selected = data.categories.find(c => /(BLACK|PRETA) \/ (Adult|Adulto)/.test(c))
        }
        // finally use the first category
        if (!selected && data.categories.length > 0) {
          selected = data.categories[0]
        }

        if (selected) {
          setSelectedRegistrationCategory(selected)
        } else {
          setSelectedRegistrationCategory(null)
          setRegistrationCompetitors(null)
        }
      }
    } catch (err) {
      handleError(err, setError)
    } finally {
      setLoading(false)
    }
  }

  const calculateEnabledAthlete = (athlete: Competitor) => {
    return athlete.rating !== null && athlete.match_count !== null && athlete.match_count > 0
  }

  return (
    <div className="brackets-content">
      <div>
        <div className="registrations">
          <div className="field">
            <div className="control">
              <input className="input" type="text" placeholder="Paste registration URL e.g. https://www.ibjjfdb.com/ChampionshipResults/NNNN/PublicRegistrations" value={registrationUrl} onKeyDown={onRegistrationUrlKeyDown} onChange={e => setRegistrationUrl(e.target.value)} />
            </div>
          </div>
          <div className="registrations-get">
            <button className="button is-info" onClick={() => getRegistrationCategories(registrationUrl)} disabled={!registrationUrl}>Get Categories</button>
          </div>
          {
            recentLinks.length > 0 &&
            <div className="field mt-4 is-horizontal">
              <div className="field-label is-normal">
                <label className="label recent-label">Recently Imported:</label>
              </div>
              <div className="field-body">
                <div className="field">
                  <div className="control">
                    <div className="select">
                      <select className="select" value={selectedRecentLink} onChange={e => {
                        if (e.target.value === '') {
                          setSelectedRecentLink('')
                          return;
                        }
                        setSelectedRecentLink(e.target.value)
                        setRegistrationUrl(e.target.value)
                        getRegistrationCategories(e.target.value)
                      }}>
                        <option value="">Choose a recent URL</option>
                        {
                          recentLinks.map(link => (
                            <option key={link.link} value={link.link}>{link.name}</option>
                          ))
                        }
                      </select>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          }
        </div>
        {
          error && <div className="notification is-danger mt-4">{error}</div>
        }
        {
        (registrationEventUrl !== null && registrationCategories !== null) && (
          <div className="category-list">
            <div className="event-name">
              <strong>{registrationEventName}</strong>
              {
                registrationEventTotal !== null && (
                  <span> - {registrationEventTotal.toLocaleString()} competitors</span>
                )
              }
            </div>
            {
              registrationCategories.length > 0 && (
                <div className="columns no-bottom-margin">
                  <div className="column column-padding is-vcentered">
                    <div className="field">
                      <div className="select">
                        <select className="select" value={selectedRegistrationCategory ?? ''} onChange={e => {setSelectedRegistrationCategory(e.target.value); }}>
                          {
                            registrationCategories.map(category => (
                              <option key={category} value={category}>{category}</option>
                            ))
                          }
                        </select>
                      </div>
                    </div>
                  </div>
                  <div className="column is-vcentered">
                  {
                    averageRating !== undefined && (
                      <span>{`Average rating: ${averageRating}`}</span>
                    )
                  }
                  </div>
                </div>
              )
            }
            {
              registrationCategories.length === 0 && (
                <div className="notification is-warning">No valid brackets found. Note: we do not load kids divisions.</div>
              )
            }
          </div>)
        }
        {
          (registrationEventUrl !== null && registrationCategories !== null && registrationCompetitors !== null) && (
            <BracketTable competitors={sortedRegistrationCompetitors}
                          showSeed={false}
                          showRank={true}
                          selectedCategory={selectedRegistrationCategory}
                          isGi={isGi(registrationEventName ?? '')}
                          athleteClicked={registrationAthleteClicked}
                          calculateEnabled={calculateEnabledAthlete} />
          )
        }
        {
          loading && <div className="bracket-loader loader mt-4"></div>
        }
      </div>
    </div>
  )
}

export default BracketRegistration;