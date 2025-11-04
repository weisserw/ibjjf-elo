import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable from './BracketTable'
import { isGi, handleError, type CompetitorsResponse, type Competitor } from './BracketUtils'
import { translateMulti, t } from '../translate'

interface RegistrationCategoriesResponse {
  event_name?: string
  total_competitors?: number
  categories?: string[]
  error?: string
}

export interface UpcomingLink {
  name: string
  link: string
}

interface UpcomingLinksResponse {
  links?: UpcomingLink[]
}

function BracketRegistration() {
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  const {
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
    bracketRegistrationUpcomingLinks: upcomingLinks,
    setBracketRegistrationUpcomingLinks: setUpcomingLinks,
    bracketRegistrationSelectedUpcomingLink: selectedUpcomingLink,
    setBracketRegistrationSelectedUpcomingLink: setSelectedUpcomingLink,
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
    const getUpcomingLinks = async () => {
      const { data } = await axios.get<UpcomingLinksResponse>('/api/brackets/registrations/links');

      if (data.links) {
        setUpcomingLinks(data.links)
      }
    }
    getUpcomingLinks()
  }, [])

  const registrationAthleteClicked = (ev: React.MouseEvent<HTMLAnchorElement>, slug: string) => {
    ev.preventDefault()
    
    setActiveTab(isGi(registrationEventName) ? 'Gi' : 'No Gi');
    navigate('/athlete/' + encodeURIComponent(slug));
  }

  const sortedRegistrationCompetitors = useMemo(() => {
    if (registrationCompetitors === null) {
      return null
    }
    return [...registrationCompetitors].sort((a, b) => {
      const aRating = a.ordinal ?? -1;
      const bRating = b.ordinal ?? -1;
      if (aRating === bRating) {
        return a.name.localeCompare(b.name)
      } else {
        return aRating - bRating
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

        if (!selectedRegistrationCategory || !data.categories.includes(selectedRegistrationCategory)) {
          let selected: string | null | undefined = null

          selected = data.categories.find(c => /(BLACK|PRETA) \/ (Adult|Adulto) \/ (Male|Masculino) \/ (Middle|Médio)/.test(c))

          // otherwise use the first adult black category
          if (!selected) {
            selected = data.categories.find(c => /(BLACK|PRETA) \/ Adult/.test(c))
          }

          // otherwise use master 1
          if (!selected) {
            selected = data.categories.find(c => /(BLACK|PRETA) \/ Master 1 \/ (Male|Masculino) \/ (Middle|Médio)/.test(c))
          }
          if (!selected) {
            selected = data.categories.find(c => /(BLACK|PRETA) \/ Master 1/.test(c))
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

  const showRatings = useMemo(() => {
    if (selectedRegistrationCategory) {
      return !/Teen/.test(selectedRegistrationCategory)
    }
    return true
  }, [selectedRegistrationCategory])

  useEffect(() => {
    if (selectedUpcomingLink) {
      getRegistrationCategories(selectedUpcomingLink)
    }
  }, [selectedUpcomingLink])

  return (
    <div className="brackets-content">
      <div>
        <div className="registrations">
          <p className="mb-2">
            {t("This tool imports registrations from the IBJJF registration system and displays the current ratings of the competitors. To view registrations, select an upcoming event from the list below")}:
          </p>
          <div className="field is-horizontal upcoming-label">
            <div className="field-label is-normal">
              <label className="label upcoming-label">{t("Upcoming tournaments")}:</label>
            </div>
            <div className="field-body upcoming-field-body">
              <div className="field upcoming-field">
                <div className="control">
                  <div className="select">
                    <select className="select" disabled={!upcomingLinks.length} value={selectedUpcomingLink} onChange={e => {
                      if (e.target.value === '') {
                        setSelectedUpcomingLink('')
                        return;
                      }
                      setSelectedUpcomingLink(e.target.value)
                    }}>
                      <option value="">{t("Choose a tournament")}</option>
                      {
                        upcomingLinks.map(link => (
                          <option key={link.link} value={link.link}>{link.name}</option>
                        ))
                      }
                    </select>
                  </div>
                </div>
              </div>
            </div>
          </div>
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
                  <span> - {registrationEventTotal.toLocaleString()} {t("competitors")}</span>
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
                              <option key={category} value={category}>{translateMulti(category)}</option>
                            ))
                          }
                        </select>
                      </div>
                    </div>
                  </div>
                  <div className="column is-vcentered">
                  {
                    (showRatings && averageRating !== undefined) && (
                      <span>{`${t("Average rating")}: ${averageRating}`}</span>
                    )
                  }
                  </div>
                </div>
              )
            }
            {
              registrationCategories.length === 0 && (
                <div className="notification is-warning">{t("No valid brackets found. Note: we do not load age divisions younger than Teen 1.")}</div>
              )
            }
          </div>)
        }
        {
          registrationCategories?.some(c => /Teen/.test(c)) && (
            <div className="notification is-warning mt-4">{t("Note: we do not load age divisions younger than Teen 1.")}</div>
          )
        }
        {
          (registrationEventUrl !== null && registrationCategories !== null && registrationCompetitors !== null) && (
            <BracketTable competitors={sortedRegistrationCompetitors}
                          showSeed={false}
                          showRank={true}
                          selectedCategory={selectedRegistrationCategory}
                          showRatings={showRatings}
                          belt={selectedRegistrationCategory ? selectedRegistrationCategory.split(' / ')[0] : ''}
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