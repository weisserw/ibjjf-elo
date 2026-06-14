import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent } from 'react'
import axios from 'axios'
import Autosuggest from 'react-autosuggest'
import debounce from 'lodash/debounce'
import type { Competitor, CompetitorsResponse } from './BracketUtils'
import { t } from '../translate'
import { axiosErrorToast, renderAthleteSuggestion, type AthleteSuggestion } from '../utils'

export interface HypotheticalSeedResponse extends CompetitorsResponse {
  hypothetical_athlete_id?: string
}

interface HypotheticalAthleteSearchProps {
  competitors: Competitor[] | null
  selectedCategory: string | null
  link: string
  gi: boolean
  onHypotheticalSeed: (data: HypotheticalSeedResponse) => void
}

function normalizedAthleteKey(value: string | null | undefined): string {
  return (value ?? '').trim().toLowerCase().replace(/\s+/g, ' ')
}

function HypotheticalAthleteSearch({
  competitors,
  selectedCategory,
  link,
  gi,
  onHypotheticalSeed,
}: HypotheticalAthleteSearchProps) {
  const [athleteSearchValue, setAthleteSearchValue] = useState('')
  const [athleteSuggestions, setAthleteSuggestions] = useState<AthleteSuggestion[]>([])
  const [hypotheticalLoading, setHypotheticalLoading] = useState(false)
  const requestSeq = useRef(0)

  const divisionGender = selectedCategory ? selectedCategory.split(' / ')[2] : null

  const registeredAthleteKeys = useMemo(() => {
    const names = new Set<string>()
    const slugs = new Set<string>()
    for (const competitor of competitors ?? []) {
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
    return () => {
      debouncedGetAthleteSuggestions.cancel()
    }
  }, [debouncedGetAthleteSuggestions])

  useEffect(() => {
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
        axiosErrorToast({ response: { data } })
      } else if (data.competitors) {
        onHypotheticalSeed(data)
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
  )
}

export default HypotheticalAthleteSearch
