import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable from './BracketTable'
import EliteTable, { type EliteAthlete } from './EliteTable'
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
  const [elitesLoading, setElitesLoading] = useState(false)
  const [elites, setElites] = useState<EliteAthlete[] | null>(null)
  const [eliteNote, setEliteNote] = useState<string | null>(null);
  const [elitesByLink, setElitesByLink] = useState<
    Record<string, { data: {elites: EliteAthlete[]; note: string | null; }; fetchedAt: number }>
  >({})

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
    bracketRegistrationViewMode: viewMode,
    setBracketRegistrationViewMode: setViewMode,
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

  const registrationDivisionClicked = (ev: React.MouseEvent<HTMLAnchorElement>, category: string) => {
    ev.preventDefault()

    setViewMode('all')
    setSelectedRegistrationCategory(category)
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

  const divisionCount = useMemo(() => registrationCompetitors?.length ?? null, [registrationCompetitors])
  const elitesCount = useMemo(() => elites?.length ?? null, [elites])

  const averageRating = useMemo(() => {
    if (viewMode === 'all') {
      if (registrationCompetitors === null || registrationCompetitors.length === 0) {
        return undefined
      }
      const ratings = registrationCompetitors.map(c => c.rating).filter(r => r !== undefined && r !== null) as number[]
      if (ratings.length === 0) {
        return undefined
      }
      const sum = ratings.reduce((a, b) => a + b, 0)
      return Math.round(sum / ratings.length)
    } else {
      if (elites === null || elites.length === 0) {
        return undefined
      }
      const ratings = elites.map(c => c.rating).filter(r => r !== undefined && r !== null) as number[]
      if (ratings.length === 0) {
        return undefined
      }
      const sum = ratings.reduce((a, b) => a + b, 0)
      return Math.round(sum / ratings.length)
    }
  }, [registrationCompetitors, elites, viewMode])

  const getRegistrationCategories = async (url: string) => {
    setLoading(true)
    setElites(null)
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

  useEffect(() => {
    if (viewMode !== 'elites' || !registrationEventUrl) {
      return
    }

    const link = registrationEventUrl
    const cached = elitesByLink[link]
    const now = Date.now()
    const tenMinutesMs = 10 * 60 * 1000
    if (cached && now - cached.fetchedAt < tenMinutesMs) {
      setElites(cached.data.elites)
      setEliteNote(cached.data.note)
      return
    }

    let cancelled = false

    const fetchElites = async () => {
      setElitesLoading(true)
      try {
        const { data } = await axios.get<{ elites?: EliteAthlete[]; note?: string; error?: string }>(
          '/api/brackets/registrations/elites',
          { params: { link } }
        )
        if (cancelled) return
        if (data.error) {
          setElites(null)
          setEliteNote(null);
          setError(data.error)
        } else if (data.elites) {
          const elitesData = data.elites ?? []
          setElites(elitesData)
          setEliteNote(data.note ?? null);
          setElitesByLink(prev => ({
            ...prev,
            [link]: { data: { elites: elitesData, note: data.note ?? null }, fetchedAt: Date.now() },
          }))
          setError(null)
        } else {
          const elitesData: EliteAthlete[] = []
          setElites(elitesData)
          setEliteNote(null);
          setElitesByLink(prev => ({
            ...prev,
            [link]: { data: { elites: elitesData, note: null }, fetchedAt: Date.now() },
          }))
        }
      } catch (err) {
        if (!cancelled) {
          handleError(err, setError)
        }
      } finally {
        if (!cancelled) {
          setElitesLoading(false)
        }
      }
    }

    void fetchElites()

    return () => {
      cancelled = true
    }
  }, [viewMode, registrationEventUrl, elitesByLink])

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
            <div className="competitor-count">
              {
                registrationEventTotal !== null && (
                  <span>Total Competitors: {registrationEventTotal.toLocaleString()}</span>
                )
              }
            </div>
            {
              (registrationCategories.length > 0 && viewMode !== 'elites') && (
                <div className="category-view">
                  <div className="category-picker">
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
                  {
                    (showRatings && averageRating !== undefined) && (
                      <div className="average-rating">
                        <span>{`${t("Average rating")}: ${averageRating}`}</span>
                      </div>
                    )
                  }
                </div>
              )
            }
            {
              registrationCategories.length > 0 && (
                <div className="view-mode-switcher">
                  {(viewMode === 'elites' && eliteNote) && (
                    <div>{eliteNote}</div>
                  )}
                  <div className="buttons has-addons is-toggle is-small no-wrap seg-control" role="radiogroup">
                    <button
                      className={`button ${viewMode === 'all' ? 'is-link is-light is-selected' : ''}`}
                      style={{ whiteSpace: 'nowrap' }}
                      aria-pressed={viewMode === 'all'}
                      aria-controls="all-panel"
                      aria-label="Division"
                      onClick={() => setViewMode('all')}
                    >
                      <span className="seg-label">{t('Division')}</span>
                      {(divisionCount !== null && viewMode === 'all') && (
                        <span className="seg-count" style={{ marginLeft: 6 }}>{`(${divisionCount.toLocaleString()})`}</span>
                      )}
                    </button>
                    <button
                      className={`button ${viewMode === 'elites' ? 'is-link is-light is-selected' : ''} ${elitesLoading ? 'is-loading' : ''}`}
                      style={{ whiteSpace: 'nowrap' }}
                      aria-pressed={viewMode === 'elites'}
                      aria-controls="elites-panel"
                      aria-label="Elites"
                      disabled={elites !== null && elites.length === 0}
                      onClick={() => setViewMode('elites')}
                    >
                      <span className="seg-label">{t('Elites')}</span>
                      {(elitesCount !== null && viewMode === 'elites') && (
                        <span className="seg-count" style={{ marginLeft: 6 }}>{`(${elitesCount.toLocaleString()})`}</span>
                      )}
                    </button>
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
          viewMode === 'all' && (registrationEventUrl !== null && registrationCategories !== null && registrationCompetitors !== null) && (
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
          viewMode === 'elites' && registrationEventUrl !== null && elites !== null && (
            <EliteTable elites={elites}
                        isGi={isGi(registrationEventName ?? '')}
                        athleteClicked={registrationAthleteClicked}
                        divisionClicked={registrationDivisionClicked} />
          )
        }
        {
          (loading || elitesLoading) && <div className="bracket-loader loader mt-4"></div>
        }
      </div>
    </div>
  )
}

export default BracketRegistration;