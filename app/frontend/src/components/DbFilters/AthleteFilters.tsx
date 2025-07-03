import { useState, useEffect, useCallback } from 'react';
import debounce from 'lodash/debounce';
import Autosuggest from 'react-autosuggest';
import axios from 'axios';
import { axiosErrorToast } from '../../utils';
import { FilterKeys } from './filterTypes';

interface AthleteFiltersProps {
  filters: any;
  setFilters: (filters: any) => void;
  onClearProps: (propnames: FilterKeys[]) => void;
  debouncedOnChange: (key: FilterKeys, value: any) => void;
}

function AthleteFilters({ filters, setFilters, onClearProps, debouncedOnChange }: AthleteFiltersProps) {
  const [athleteName, setAthleteName] = useState(filters.athlete_name || '');
  const [ratingStart, setRatingStart] = useState(filters.rating_start || '');
  const [ratingEnd, setRatingEnd] = useState(filters.rating_end || '');
  const [athleteSuggestions, setAthleteSuggestions] = useState<string[]>([]);

  // Set the control state for debounced controls when the filters change
  useEffect(() => {
    if (filters.athlete_name !== athleteName) {
      setAthleteName(filters.athlete_name || '');
    }
  }, [filters.athlete_name]);
  
  useEffect(() => {
    if (filters.rating_start !== ratingStart) {
      setRatingStart(filters.rating_start || '');
    }
  }, [filters.rating_start]);
  
  useEffect(() => {
    if (filters.rating_end !== ratingEnd) {
      setRatingEnd(filters.rating_end || '');
    }
  }, [filters.rating_end]);

  const getAthleteSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/athletes?allowteen=true&search=${encodeURIComponent(value)}`);
      setAthleteSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetAthleteSuggestions = useCallback(debounce(getAthleteSuggestions, 300, {trailing: true}), []);

  return (
    <div className="db-filters-content w-full">
      <div className="columns is-mobile is-multiline">
        <div className="column is-full-mobile">
          <div className="field">
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4, justifyContent: 'space-between' }}>
              <label className="label" style={{ marginBottom: 0 }}>Athlete Name</label>
              <button
                className="button is-small is-light"
                style={{ marginLeft: 8 }}
                onClick={() => {
                  setAthleteName('');
                  onClearProps(['athlete_name']);
                }}
              >Clear</button>
            </div>
            <div className="control">
              <Autosuggest suggestions={athleteSuggestions}
                           onSuggestionsFetchRequested={debouncedGetAthleteSuggestions}
                           onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                           multiSection={false}
                           getSuggestionValue={(suggestion) => '"' + suggestion + '"'}
                           renderSuggestion={(suggestion) => suggestion}
                           inputProps={{
                             className: "input is-small",
                             value: athleteName,
                             placeholder: "Search athlete name",
                             onChange: (_: any, { newValue }) => {
                               setAthleteName(newValue);
                               debouncedOnChange('athlete_name', newValue);
                             }
                           }} />
            </div>
          </div>
        </div>
        <div className="column is-full-mobile">
          <div className="field">
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4, justifyContent: 'space-between' }}>
              <label className="label" style={{ marginBottom: 0 }}>Rating Range</label>
              <button
                className="button is-small is-light"
                style={{ marginLeft: 8 }}
                onClick={() => {
                  setRatingStart('');
                  setRatingEnd('');
                  onClearProps(['rating_start', 'rating_end']);
                }}
              >Clear</button>
            </div>
            <div className="field has-addons">
              <div className="control is-expanded">
                <input
                  className="input is-small"
                  type="number"
                  value={ratingStart}
                  placeholder="Min rating"
                  onChange={(e) => {
                    setRatingStart(e.target.value);
                    debouncedOnChange('rating_start', e.target.value);
                  }}
                />
              </div>
              <div className="px-3">
                -
              </div>
              <div className="control is-expanded">
                <input
                  className="input is-small"
                  type="number"
                  value={ratingEnd}
                  placeholder="Max rating"
                  onChange={(e) => {
                    setRatingEnd(e.target.value);
                    debouncedOnChange('rating_end', e.target.value);
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default AthleteFilters;