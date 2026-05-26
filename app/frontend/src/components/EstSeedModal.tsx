import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import Autosuggest from 'react-autosuggest'
import debounce from 'lodash/debounce'
import type { Competitor, CompetitorsResponse, SideSwap } from './BracketUtils'
import AthleteMedalBreakdown from './AthleteMedalBreakdown'
import { t, type translationKeys } from '../translate'
import { axiosErrorToast, renderAthleteSuggestion, type AthleteSuggestion } from '../utils'

interface EstSeedModalProps {
  competitors: Competitor[]
  selectedCategory: string | null
  sideSwaps: SideSwap[]
  link: string
  gi: boolean
  onClose: () => void
}

type ColumnType = 'number' | 'bool' | 'year'

interface ColumnSpec {
  key: keyof Competitor
  label: string
  type: ColumnType
}

interface HypotheticalSeedResponse extends CompetitorsResponse {
  hypothetical_athlete_id?: string
}

interface HypotheticalCompetitor extends Competitor {
  hypothetical?: boolean
}

// Frontend-only mirror of the python sort-criteria mapping in
// app/seeding.py:add_estimated_seeds. The crc32 tie-break is intentionally
// excluded.
function columnsForDivision(selectedCategory: string | null): ColumnSpec[] {
  if (!selectedCategory) return []
  const parts = selectedCategory.split(' / ')
  const belt = parts[0] ?? ''
  const age = parts[1] ?? ''
  const weight = parts[3] ?? ''

  const isOpen = /Open/i.test(weight)
  const isBlack = belt === 'BLACK' || belt === 'PRETA'
  const isAdult = age === 'Adult' || age === 'Adulto'
  const isAdultBlack = isAdult && isBlack
  const masterMatch = /^Master (\d+)$/.exec(age)
  const masterLevel = masterMatch ? parseInt(masterMatch[1], 10) : null
  const isMasterBlack = masterLevel !== null && isBlack

  const num = (key: keyof Competitor, label: string): ColumnSpec => ({ key, label, type: 'number' })
  const bool = (key: keyof Competitor, label: string): ColumnSpec => ({ key, label, type: 'bool' })
  const year = (key: keyof Competitor, label: string): ColumnSpec => ({ key, label, type: 'year' })

  if (isAdultBlack && isOpen) {
    return [
      bool('world_champion_recent', t('WC (Last 3)')),
      year('last_world_title_year', t('Last Title')),
      num('grand_slam_open_class_points', t('GS Open Pts')),
      num('grand_slam_points', t('GS Pts')),
      bool('world_champion_4_years_ago', t('WC 4y Ago')),
      bool('world_champion_5_years_ago', t('WC 5y Ago')),
      bool('previous_brown_world_champion', t('Brown WC')),
      year('former_world_champion', t('Former WC')),
      num('open_class_points', t('Open Pts')),
      num('points', t('Pts')),
    ]
  }
  if (isAdultBlack) {
    return [
      bool('world_champion_recent', t('WC (Last 3)')),
      year('last_world_title_year', t('Last Title')),
      num('grand_slam_points', t('GS Pts')),
      bool('world_champion_4_years_ago', t('WC 4y Ago')),
      bool('world_champion_5_years_ago', t('WC 5y Ago')),
      bool('previous_brown_world_champion', t('Brown WC')),
      year('former_world_champion', t('Former WC')),
      num('points', t('Pts')),
    ]
  }
  if (isMasterBlack) {
    const masters: ColumnSpec[] = []
    for (let i = 1; i <= (masterLevel as number); i++) {
      masters.push(bool(`master_${i}_world_champion` as keyof Competitor, t(`M${i} WC` as translationKeys)))
    }
    if (isOpen) {
      return [
        bool('adult_world_champion', t('Adult WC')),
        ...masters,
        num('grand_slam_open_class_points', t('GS Open Pts')),
        num('grand_slam_points', t('GS Pts')),
        num('open_class_points', t('Open Pts')),
        num('points', t('Pts')),
      ]
    }
    return [
      bool('adult_world_champion', t('Adult WC')),
      ...masters,
      num('grand_slam_points', t('GS Pts')),
      num('points', t('Pts')),
    ]
  }
  if (isOpen) {
    return [
      num('grand_slam_open_class_points', t('GS Open Pts')),
      num('grand_slam_points', t('GS Pts')),
      num('open_class_points', t('Open Pts')),
      num('points', t('Pts')),
    ]
  }
  return [
    num('grand_slam_points', t('GS Pts')),
    num('points', t('Pts')),
  ]
}

function renderCell(value: unknown, type: ColumnType): string {
  if (type === 'bool') return value ? '✓' : ''
  if (type === 'year') return value == null ? '' : String(value)
  if (value == null) return ''
  return String(value)
}

function normalizedAthleteKey(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
}

function EstSeedModal({ competitors, selectedCategory, link, gi, onClose }: EstSeedModalProps) {
  const columns = useMemo(() => columnsForDivision(selectedCategory), [selectedCategory])
  const [selectedAthlete, setSelectedAthlete] = useState<Competitor | null>(null)
  const [athleteSearchValue, setAthleteSearchValue] = useState('')
  const [athleteSuggestions, setAthleteSuggestions] = useState<AthleteSuggestion[]>([])
  const [hypotheticalCompetitors, setHypotheticalCompetitors] = useState<HypotheticalCompetitor[] | null>(null)
  const [hypotheticalAthleteId, setHypotheticalAthleteId] = useState<string | null>(null)
  const [hypotheticalLoading, setHypotheticalLoading] = useState(false)
  const requestSeq = useRef(0)

  const divisionGender = selectedCategory ? selectedCategory.split(' / ')[2] : null

  const registeredAthleteKeys = useMemo(() => {
    const names = new Set<string>()
    const slugs = new Set<string>()
    for (const competitor of competitors) {
      const name = normalizedAthleteKey(competitor.name)
      const personalName = normalizedAthleteKey(competitor.personal_name)
      if (name) names.add(name)
      if (personalName) names.add(personalName)
      if (competitor.slug) slugs.add(competitor.slug)
    }
    return { names, slugs }
  }, [competitors])

  const isRegisteredSuggestion = useCallback((suggestion: AthleteSuggestion) => {
    if (suggestion.slug && registeredAthleteKeys.slugs.has(suggestion.slug)) return true
    const name = normalizedAthleteKey(suggestion.name)
    const personalName = normalizedAthleteKey(suggestion.personal_name)
    return (name !== '' && registeredAthleteKeys.names.has(name)) || (
      personalName !== '' && registeredAthleteKeys.names.has(personalName)
    )
  }, [registeredAthleteKeys])

  const sorted = useMemo(() => {
    return [...(hypotheticalCompetitors ?? competitors)].sort((a, b) => {
      const aSeed = a.est_seed ?? Number.MAX_SAFE_INTEGER
      const bSeed = b.est_seed ?? Number.MAX_SAFE_INTEGER
      return aSeed - bSeed
    })
  }, [competitors, hypotheticalCompetitors])

  const debouncedGetAthleteSuggestions = useMemo(
    () => debounce(async ({ value }: { value: string }) => {
      if (!value.trim() || !divisionGender) {
        setAthleteSuggestions([])
        return
      }

      try {
        const response = await axios.get<AthleteSuggestion[]>('/api/athletes', {
          params: {
            search: value,
            gender: divisionGender,
            gi: gi ? 'true' : 'false',
          },
        })
        setAthleteSuggestions(response.data.filter(suggestion => !isRegisteredSuggestion(suggestion)))
      } catch (error) {
        axiosErrorToast(error)
      }
    }, 300, { trailing: true }),
    [divisionGender, gi, isRegisteredSuggestion],
  )

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (selectedAthlete) {
          setSelectedAthlete(null)
        } else {
          onClose()
        }
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, selectedAthlete])

  useEffect(() => {
    return () => {
      debouncedGetAthleteSuggestions.cancel()
    }
  }, [debouncedGetAthleteSuggestions])

  useEffect(() => {
    setHypotheticalCompetitors(null)
    setHypotheticalAthleteId(null)
    setAthleteSearchValue('')
    setAthleteSuggestions([])
  }, [selectedCategory, link, gi])

  const onAthleteSuggestionSelected = async (suggestion: AthleteSuggestion) => {
    if (!suggestion.slug || !selectedCategory) return
    if (isRegisteredSuggestion(suggestion)) {
      setAthleteSuggestions([])
      return
    }

    const currentRequest = requestSeq.current + 1
    requestSeq.current = currentRequest
    setAthleteSearchValue(renderAthleteSuggestion(suggestion))
    setAthleteSuggestions([])
    setHypotheticalLoading(true)

    try {
      const { data } = await axios.get<HypotheticalSeedResponse>(
        '/api/brackets/registrations/hypothetical_seed',
        {
          params: {
            link,
            division: selectedCategory,
            gi: gi ? 'true' : 'false',
            athlete_slug: suggestion.slug,
          },
        },
      )

      if (currentRequest !== requestSeq.current) return

      if (data.error) {
        setHypotheticalCompetitors(null)
        setHypotheticalAthleteId(null)
        axiosErrorToast({ response: { data } })
      } else if (data.competitors) {
        setHypotheticalCompetitors(data.competitors as HypotheticalCompetitor[])
        setHypotheticalAthleteId(data.hypothetical_athlete_id ?? null)
        setAthleteSearchValue('')
      }
    } catch (error) {
      if (currentRequest === requestSeq.current) {
        axiosErrorToast(error)
      }
    } finally {
      if (currentRequest === requestSeq.current) {
        setHypotheticalLoading(false)
      }
    }
  }

  const renderSearchSuggestion = (suggestion: AthleteSuggestion) => (
    <div className="est-seed-athlete-suggestion">
      {renderAthleteSuggestion(suggestion)}
    </div>
  )

  return (
    <div className="modal is-active est-seed-modal">
      <div className="modal-background" onClick={onClose}></div>
      <div className="modal-content est-seed-modal-content">
        {!selectedAthlete && (
          <button
            className="delete is-medium est-seed-modal-close"
            aria-label="close"
            onClick={onClose}
          ></button>
        )}
        <div className="est-seed-modal-body">
          {selectedAthlete ? (
            <>
              <div className="is-flex is-align-items-center mb-3">
                <button
                  className="button is-small is-light mr-3 est-seed-back-button"
                  aria-label={t('Back')}
                  onClick={() => setSelectedAthlete(null)}
                >
                  <span className="icon">
                    <i className="fas fa-arrow-left" aria-hidden="true"></i>
                  </span>
                </button>
                <h2 className="title is-5 mb-0">
                  {selectedAthlete.personal_name ?? selectedAthlete.name}
                </h2>
              </div>
              {selectedAthlete.id && selectedCategory && (
                <AthleteMedalBreakdown
                  athleteId={selectedAthlete.id}
                  link={link}
                  division={selectedCategory}
                  gi={gi}
                />
              )}
            </>
          ) : (
            <>
              <h2 className="title is-5">{t('Estimated Seeding')}</h2>
              <div className="table-container">
                <table className="table is-fullwidth est-seed-modal-table">
                  <thead>
                    <tr>
                      <th className="has-text-right">#</th>
                      <th>{t('Name')}</th>
                      <th>{t('Team')}</th>
                      {columns.map(c => (
                        <th
                          key={c.key as string}
                          className={`no-wrap ${c.type === 'bool' ? 'has-text-centered' : 'has-text-right'}`}
                        >
                          {c.label}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((c, i) => {
                      const displayName = c.personal_name ? c.personal_name : c.name
                      const isHypothetical = Boolean((c as HypotheticalCompetitor).hypothetical) || (
                        hypotheticalAthleteId !== null && c.id === hypotheticalAthleteId
                      )
                      return (
                        <tr
                          key={`${c.name}-${c.est_seed ?? ''}-${isHypothetical ? 'hypothetical' : 'registered'}`}
                          className={isHypothetical ? 'est-seed-hypothetical-row' : undefined}
                        >
                          <td className="has-text-right">{i + 1}</td>
                          <td>
                            {c.id ? (
                              <button
                                type="button"
                                className="est-seed-athlete-link"
                                onClick={() => setSelectedAthlete(c)}
                              >
                                {displayName}
                              </button>
                            ) : (
                              displayName
                            )}
                          </td>
                          <td>{c.team}</td>
                          {columns.map(col => (
                            <td
                              key={col.key as string}
                              className={col.type === 'bool' ? 'has-text-centered' : 'has-text-right'}
                            >
                              {renderCell(c[col.key], col.type)}
                            </td>
                          ))}
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
              <div className="est-seed-hypothetical-search">
                <Autosuggest
                  suggestions={athleteSuggestions}
                  onSuggestionsFetchRequested={debouncedGetAthleteSuggestions}
                  onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                  multiSection={false}
                  getSuggestionValue={(suggestion) => renderAthleteSuggestion(suggestion)}
                  renderSuggestion={renderSearchSuggestion}
                  onSuggestionSelected={(_event: FormEvent<HTMLElement>, { suggestion }: { suggestion: AthleteSuggestion }) => {
                    void onAthleteSuggestionSelected(suggestion)
                  }}
                  inputProps={{
                    className: 'input est-seed-hypothetical-input',
                    value: athleteSearchValue,
                    placeholder: t('Add hypothetical athlete') + '...',
                    onChange: (_event: FormEvent<HTMLElement>, { newValue }: { newValue: string }) => setAthleteSearchValue(newValue),
                  }}
                />
                {hypotheticalLoading && <span className="loader est-seed-hypothetical-loader"></span>}
              </div>
            </>
          )}
          <p className="est-seed-disclaimer mt-4">
            {t('Estimated seeding is a BETA feature and can vary from the actual seeding for a division for many reasons, including but not limited to: missing medals in our system, athletes changing teams or gaining points before an event, and differences in tie breaks. These seeds should not be mistaken for official IBJJF seeds.')}
          </p>
        </div>
      </div>
    </div>
  )
}

export default EstSeedModal
