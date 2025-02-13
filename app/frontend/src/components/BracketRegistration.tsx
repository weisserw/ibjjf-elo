import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable from './BracketTable'
import { isGi, handleError, type CompetitorsResponse } from './BracketUtils'

interface RegistrationCategoriesResponse {
  event_name?: string
  total_competitors?: number
  categories?: string[]
  error?: string
}

function BracketRegistration() {
  const [error, setError] = useState<string | null>(null)
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

  const registrationAthleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => {
    ev.preventDefault()
    setFilters({
      athlete_name: name,
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

  const onRegistrationUrlKeyDown = (ev: React.KeyboardEvent<HTMLInputElement>) => {
    if (ev.key === 'Enter' && registrationUrl) {
      getRegistrationCategories()
    }
  }

  const getRegistrationCategories = async () => {
    setLoading(true)
    try {
      const { data } = await axios.get<RegistrationCategoriesResponse>('/api/brackets/registrations/categories', {
        params: {
          link: registrationUrl
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
        setRegistrationEventUrl(registrationUrl)
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
            <button className="button is-info" onClick={getRegistrationCategories} disabled={!registrationUrl}>Get Categories</button>
          </div>
        </div>
        {
          error && <div className="notification is-danger mt-4">{error}</div>
        }
        {
        (registrationEventUrl !== null && registrationCategories !== null) && (
          <div className="category-list">
            <p>
              <strong>{registrationEventName}</strong>
              {
                registrationEventTotal !== null && (
                  <span> - {registrationEventTotal.toLocaleString()} competitors</span>
                )
              }
            </p>
            {
              registrationCategories.length > 0 && (
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
                          athleteClicked={registrationAthleteClicked} />
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