import { useState, useMemo, useEffect } from 'react'
import axios from 'axios'
import classNames from 'classnames'
import { useAppContext } from '../AppContext'
import { useNavigate } from 'react-router-dom'
import BracketTable, { type SortColumn } from './BracketTable'
import BracketTree, { type SeedHighlight } from './BracketTree'
import EliteTable, { type EliteAthlete } from './EliteTable'
import EstSeedModal from './EstSeedModal'
import { isGi, handleError, createMatchesFromSeeds, createSnakeBracketSlots, type CompetitorsResponse, type Competitor } from './BracketUtils'
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
  const [estSeedModalOpen, setEstSeedModalOpen] = useState(false)
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
    bracketRegistrationSideSwaps: sideSwaps,
    setBracketRegistrationSideSwaps: setSideSwaps,
    bracketRegistrationSideSwapBailoutTeams: sideSwapBailoutTeams,
    setBracketRegistrationSideSwapBailoutTeams: setSideSwapBailoutTeams,
    bracketRegistrationSlots: bracketSlots,
    setBracketRegistrationSlots: setBracketSlots,
    bracketRegistrationMatchCount: bracketMatchCount,
    setBracketRegistrationMatchCount: setBracketMatchCount,
    bracketRegistrationUpcomingLinks: upcomingLinks,
    setBracketRegistrationUpcomingLinks: setUpcomingLinks,
    bracketRegistrationSelectedUpcomingLink: selectedUpcomingLink,
    setBracketRegistrationSelectedUpcomingLink: setSelectedUpcomingLink,
    bracketRegistrationViewMode: viewMode,
    setBracketRegistrationViewMode: setViewMode,
    bracketRegistrationViewTab: viewTab,
    setBracketRegistrationViewTab: setViewTab,
    bracketRegistrationSortColumn: sortColumn,
    setBracketRegistrationSortColumn: setSortColumn,
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
        setSideSwaps([])
        setSideSwapBailoutTeams([])
        setBracketSlots(null)
        setBracketMatchCount(null)
        setError(data.error)
      } else if (data.competitors) {
        setRegistrationCompetitors(data.competitors)
        setSideSwaps(data.side_swaps ?? [])
        setSideSwapBailoutTeams(data.side_swap_bailout_teams ?? [])
        setBracketSlots(data.bracket_slots ?? null)
        setBracketMatchCount(data.bracket_match_count ?? null)
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

  const columnClicked = (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => {
    ev.preventDefault()
    setSortColumn(column)
  }

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

  const showRatings = useMemo(() => {
    if (selectedRegistrationCategory) {
      return !/Teen/.test(selectedRegistrationCategory)
    }
    return true
  }, [selectedRegistrationCategory])

  const usableSortColumn = useMemo(() => {
    let column = sortColumn
    if (!showRatings && column === 'rating') {
      column = 'est_seed'
    }
    return column
  }, [sortColumn, showRatings])

  const sortedRegistrationCompetitors = useMemo(() => {
    if (registrationCompetitors === null) {
      return null
    }
    return [...registrationCompetitors].sort((a, b) => {
      const aRating = a.ordinal ?? -1;
      const bRating = b.ordinal ?? -1;
      const aEst = a.est_seed ?? Number.MAX_SAFE_INTEGER;
      const bEst = b.est_seed ?? Number.MAX_SAFE_INTEGER;
      if (usableSortColumn === 'est_seed') {
        if (aEst === bEst) {
          return aRating - bRating
        }
        return aEst - bEst
      }
      if (aRating === bRating) {
        return a.name.localeCompare(b.name)
      }
      return aRating - bRating
    });
  }, [registrationCompetitors, usableSortColumn])

  const seededBracket = useMemo(() => {
    if (!sortedRegistrationCompetitors || !bracketSlots || bracketMatchCount == null) return null;
    return createMatchesFromSeeds(sortedRegistrationCompetitors, bracketSlots, bracketMatchCount, sideSwaps);
  }, [sortedRegistrationCompetitors, bracketSlots, bracketMatchCount, sideSwaps])

  const nativeSeedByCompetitor = useMemo(() => {
    const result = new Map<Competitor, number>();
    if (!registrationCompetitors || !showRatings) return result;

    [...registrationCompetitors]
      .sort((a, b) => {
        const aOrdinal = a.ordinal ?? Number.MAX_SAFE_INTEGER;
        const bOrdinal = b.ordinal ?? Number.MAX_SAFE_INTEGER;
        if (aOrdinal !== bOrdinal) return aOrdinal - bOrdinal;

        const aRating = a.rating ?? Number.NEGATIVE_INFINITY;
        const bRating = b.rating ?? Number.NEGATIVE_INFINITY;
        if (aRating !== bRating) return bRating - aRating;

        return a.name.localeCompare(b.name);
      })
      .forEach((competitor, index) => {
        result.set(competitor, index + 1);
      });

    return result;
  }, [registrationCompetitors, showRatings])

  const idealBracket = useMemo(() => {
    if (!registrationCompetitors || nativeSeedByCompetitor.size < 2) return null;
    const snakeSlots = createSnakeBracketSlots(nativeSeedByCompetitor.size);
    if (!snakeSlots) return null;

    return createMatchesFromSeeds(
      registrationCompetitors,
      snakeSlots.bracketSlots,
      snakeSlots.matchCount,
      [],
      competitor => nativeSeedByCompetitor.get(competitor),
    );
  }, [registrationCompetitors, nativeSeedByCompetitor])

  useEffect(() => {
    if (viewMode !== 'all') return;

    if (viewTab === 'Bracket' && seededBracket === null) {
      setViewTab(idealBracket !== null ? 'IdealBracket' : 'Table');
    } else if (viewTab === 'IdealBracket' && idealBracket === null) {
      setViewTab(seededBracket !== null ? 'Bracket' : 'Table');
    }
  }, [viewTab, seededBracket, idealBracket, viewMode, setViewTab])

  const seedHighlights = useMemo(() => {
    const result = new Map<string, SeedHighlight>();
    if (!sortedRegistrationCompetitors) return result;
    const categoryAge = selectedRegistrationCategory ? selectedRegistrationCategory.split(' / ')[1] : null;
    const isJuvenile = categoryAge === 'Juvenile' || categoryAge === 'Juvenile 1' || categoryAge === 'Juvenile 2';
    if (isJuvenile) return result;

    const swappedNames = new Set<string>();
    for (const swap of sideSwaps) {
      swappedNames.add(swap.name_a);
      swappedNames.add(swap.name_b);
    }
    for (const c of sortedRegistrationCompetitors) {
      if (c.est_seed == null) continue;
      const isSwap = swappedNames.has(c.name);
      const isTied = !!c.est_seed_tied;
      if (isSwap && isTied) result.set(c.name, 'swap-tied');
      else if (isSwap) result.set(c.name, 'swap');
      else if (isTied) result.set(c.name, 'tied');
    }
    return result;
  }, [sortedRegistrationCompetitors, sideSwaps, selectedRegistrationCategory])

  const seedSwapDescriptions = useMemo(() => {
    const result = new Map<string, string>();
    if (!sortedRegistrationCompetitors) return result;

    const competitorByName = new Map(sortedRegistrationCompetitors.map(c => [c.name, c]));
    const describe = (name: string) => {
      const competitor = competitorByName.get(name);
      if (!competitor) return name;
      const displayName = competitor.personal_name || competitor.name;
      return competitor.est_seed != null ? `${displayName} (${competitor.est_seed})` : displayName;
    }

    for (const swap of sideSwaps) {
      result.set(swap.name_a, describe(swap.name_b));
      result.set(swap.name_b, describe(swap.name_a));
    }

    return result;
  }, [sortedRegistrationCompetitors, sideSwaps])

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
        setRegistrationCompetitors(null)
        setSideSwaps([])
        setSideSwapBailoutTeams([])
        setBracketSlots(null)
        setBracketMatchCount(null)
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
            setSideSwaps([])
            setSideSwapBailoutTeams([])
            setBracketSlots(null)
            setBracketMatchCount(null)
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
            <div className="tabs bracket-view-tabs">
              <ul>
                <li className={classNames({"is-active": viewTab === 'Table'})} onClick={() => setViewTab('Table')}>
                  <a>{t("List")}</a>
                </li>
                {seededBracket !== null && (
                  <li className={classNames({"is-active": viewTab === 'Bracket'})} onClick={() => setViewTab('Bracket')}>
                    <a>{t("Predicted Bracket")}</a>
                  </li>
                )}
                {idealBracket !== null && (
                  <li className={classNames({"is-active": viewTab === 'IdealBracket'})} onClick={() => setViewTab('IdealBracket')}>
                    <a>{t("Ideal Bracket")}</a>
                  </li>
                )}
              </ul>
            </div>
          )
        }
        {
          viewTab === 'Bracket' &&
          viewMode === 'all' &&
          registrationEventUrl !== null &&
          registrationCategories !== null && (
            <p className="mt-4">
              {t("Predicted brackets are a BETA feature and may vary from the actual brackets for the event. These brackets should not be mistaken for official IBJJF brackets.")}
            </p>
          )
        }
        {
          viewTab === 'Bracket' &&
          viewMode === 'all' &&
          registrationEventUrl !== null &&
          registrationCategories !== null &&
          seededBracket !== null && (
            <BracketTree
              matches={seededBracket.matches}
              matchCount={seededBracket.matchCount}
              hasMatchNums={true}
              showSeed={true}
              showRefresh={false}
              showRatings={showRatings}
              belt={selectedRegistrationCategory ? selectedRegistrationCategory.split(' / ')[0] : ''}
              seedHighlights={seedHighlights}
              seedSwapDescriptions={seedSwapDescriptions}
              calculateClicked={() => {}}
              calculateEnabled={() => false}
            />
          )
        }
        {
          viewTab === 'IdealBracket' &&
          viewMode === 'all' &&
          registrationEventUrl !== null &&
          registrationCategories !== null &&
          idealBracket !== null && (
            <BracketTree
              matches={idealBracket.matches}
              matchCount={idealBracket.matchCount}
              hasMatchNums={true}
              showSeed={true}
              showRefresh={false}
              showRatings={showRatings}
              belt={selectedRegistrationCategory ? selectedRegistrationCategory.split(' / ')[0] : ''}
              calculateClicked={() => {}}
              calculateEnabled={() => false}
            />
          )
        }
        {
          viewTab === 'Table' && viewMode === 'all' && (registrationEventUrl !== null && registrationCategories !== null && registrationCompetitors !== null) && (
            <BracketTable competitors={sortedRegistrationCompetitors}
                          sortColumn={usableSortColumn}
                          showSeed={false}
                          showEstSeed={true}
                          onEstSeedInfoClick={() => setEstSeedModalOpen(true)}
                          showRank={true}
                          selectedCategory={selectedRegistrationCategory}
                          showRatings={showRatings}
                          belt={selectedRegistrationCategory ? selectedRegistrationCategory.split(' / ')[0] : ''}
                          isGi={isGi(registrationEventName ?? '')}
                          sideSwaps={sideSwaps}
                          sideSwapBailoutTeams={sideSwapBailoutTeams}
                          columnClicked={columnClicked}
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
        {
          estSeedModalOpen && sortedRegistrationCompetitors && (
            <EstSeedModal
              competitors={sortedRegistrationCompetitors}
              selectedCategory={selectedRegistrationCategory}
              sideSwaps={sideSwaps}
              link={registrationEventUrl ?? ''}
              gi={isGi(registrationEventName ?? '')}
              onClose={() => setEstSeedModalOpen(false)}
            />
          )
        }
      </div>
    </div>
  )
}

export default BracketRegistration;
