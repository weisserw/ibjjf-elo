import { useState, useEffect, useCallback, type ReactNode } from 'react';
import debounce from 'lodash/debounce';
import classNames from 'classnames';
import dayjs from 'dayjs';
import Autosuggest from 'react-autosuggest';
import axios from 'axios';
import { useAppContext } from '../AppContext';
import { axiosErrorToast } from '../utils';

import './DBFilters.css';

interface SectionProps {
  title: string;
  isOpen: boolean;
  isBold: boolean;
  setIsOpen(isOpen: boolean): void;
  children?: ReactNode;
}

function Section(props: SectionProps) {
  return (
    <div className="accordion-section">
      <h5 className={classNames("section-title", {"section-title-bold": props.isBold})} onClick={() => props.setIsOpen(!props.isOpen)}>
        {props.title}
        <span className={`accordion-icon ${props.isOpen ? 'is-active' : ''}`}>
          <i className={`fas fa-angle-${props.isOpen ? 'up' : 'down'}`}></i>
        </span>
      </h5>
      <hr className="section-divider" />
      {
        props.isOpen &&
        <div className="section-content">
          {props.children}
        </div>
      }
    </div>
  );
}

export interface FilterValues {
  athlete_name?: string;
  event_name?: string;
  gender_male?: boolean;
  gender_female?: boolean;
  age_adult?: boolean;
  age_master1?: boolean;
  age_master2?: boolean;
  age_master3?: boolean;
  age_master4?: boolean;
  age_master5?: boolean;
  age_master6?: boolean;
  age_master7?: boolean;
  age_juvenile?: boolean;
  belt_white?: boolean;
  belt_blue?: boolean;
  belt_purple?: boolean;
  belt_brown?: boolean;
  belt_black?: boolean;
  weight_rooster?: boolean;
  weight_light_feather?: boolean;
  weight_feather?: boolean;
  weight_light?: boolean;
  weight_middle?: boolean;
  weight_medium_heavy?: boolean;
  weight_heavy?: boolean;
  weight_super_heavy?: boolean;
  weight_ultra_heavy?: boolean;
  weight_open_class?: boolean;
  date_start?: string;
  date_end?: string;
  rating_start?: number;
  rating_end?: number;
}

export type FilterKeys = keyof FilterValues;

type DivisionFilterKeys = {
  [K in FilterKeys]: K extends `gender_${string}` | `age_${string}` | `belt_${string}` | `weight_${string}` ? K : never
}[FilterKeys];

export interface OpenFilters {
  athlete: boolean;
  event: boolean;
  division: boolean;
}

export const ageToFilter = (age: string) => `age_${age.toLowerCase().replace(' ', '')}` as DivisionFilterKeys;

export const genderToFilter = (gender: string) => `gender_${gender.toLowerCase()}` as DivisionFilterKeys;

export const beltToFilter = (belt: string) => `belt_${belt.toLowerCase()}` as DivisionFilterKeys;

export const weightToFilter = (weight: string): DivisionFilterKeys => {
  if (weight === 'Open Class Light' || weight === 'Open Class Heavy') {
    return weightToFilter('Open Class');
  }
  return `weight_${weight.toLowerCase().replace(' ', '_')}` as DivisionFilterKeys;
}

function DBFilters() {
  const {
    filters,
    setFilters,
    activeTab,
    openFilters,
    setOpenFilters,
  } = useAppContext();

  const gi = activeTab === 'Gi';

  const [isOpen, setIsOpen] = useState(true);
  const [athleteName, setAthleteName] = useState(filters.athlete_name || '');
  const [eventName, setEventName] = useState(filters.event_name || '');
  const [ratingStart, setRatingStart] = useState(filters.rating_start || '');
  const [ratingEnd, setRatingEnd] = useState(filters.rating_end || '');
  const [athleteSuggestions, setAthleteSuggestions] = useState<string[]>([]);
  const [eventSuggestions, setEventSuggestions] = useState<string[]>([]);

  const anyFiltersSet = Object.values(filters).some(value => value !== undefined);

  const anyDivisionFiltersSet = (Object.keys(filters) as FilterKeys[]).filter(
    key => key.startsWith('gender_') || key.startsWith('age_') || key.startsWith('belt_') || key.startsWith('weight_')
  ).map(key => filters[key]).some(value => value !== undefined);

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };

  const onClearProps = (propnames: FilterKeys[]) => {
    const newFilters = { ...filters };
    for (const prop of propnames) {
      delete newFilters[prop];
    }
    setFilters(newFilters);
  }

  const onClearOrAll = (propnames: DivisionFilterKeys[]) => {
    if (propnames.some(prop => filters[prop])) {
      onClearProps(propnames);
    } else {
      const newFilters = { ...filters };
      for (const prop of propnames) {
        newFilters[prop] = true;
      }
      setFilters(newFilters);
    }
  }

  const onChange = (key: FilterKeys, value: any) => {
    const newFilters = { ...filters, [key]: value };
    if (value === '' || value === false) {
      delete newFilters[key];
    }
    setFilters(newFilters);
  }

  const debouncedOnChange = useCallback(debounce(onChange, 750, {trailing: true}), [filters]);

  // Set the control state for debounced controls
  // when the filters change
  useEffect(() => {
    if (filters.athlete_name !== athleteName) {
      setAthleteName(filters.athlete_name || '');
    }
  }, [filters.athlete_name]);
  useEffect(() => {
    if (filters.event_name !== eventName) {
      setEventName(filters.event_name || '');
    }
  }, [filters.event_name]);
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
      const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
      setAthleteSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetAthleteSuggestions = useCallback(debounce(getAthleteSuggestions, 300, {trailing: true}), []);

  const getEventSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/events?search=${encodeURIComponent(value)}&gi=${gi}`);
      setEventSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetEventSuggestions = useCallback(debounce(getEventSuggestions, 300, {trailing: true}), []);

  return (
    <div className={classNames("box accordion-box", {"open": isOpen})}>
      <div className="accordion">
        <header className="accordion-header" onClick={toggleAccordion}>
          {
            anyFiltersSet ?
              <p><strong>Filters</strong></p>
            :
              <p>Filters</p>
          }
          <span className={`accordion-icon ${isOpen ? 'is-active' : ''}`}>
            <i className={`fas fa-angle-${isOpen ? 'up' : 'down'}`}></i>
          </span>
        </header>
        {isOpen && (
          <div className="accordion-body">
            <Section title="Athlete"
                     isOpen={openFilters.athlete}
                     setIsOpen={(isOpen: boolean) => setOpenFilters({ ...openFilters, athlete: isOpen })}
                     isBold={
                        !!filters.athlete_name ||
                        !!filters.rating_start ||
                        !!filters.rating_end
                     }>
              <div className="field is-grouped">
                <div className="control is-expanded">
                  <Autosuggest suggestions={athleteSuggestions}
                               onSuggestionsFetchRequested={debouncedGetAthleteSuggestions}
                               onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                               multiSection={false}
                               getSuggestionValue={(suggestion) => suggestion}
                               renderSuggestion={(suggestion) => suggestion}
                               inputProps={{
                                 className: "input is-small",
                                 value: athleteName,
                                 placeholder: "Athlete Name",
                                 onChange: (_: any, { newValue }) => {
                                   setAthleteName(newValue);
                                   debouncedOnChange('athlete_name', newValue);
                                 }
                               }} />
                </div>
                <div className="control">
                  <button className="button is-small is-light" onClick={() => {
                    setAthleteName('');
                    onClearProps(['athlete_name']);
                  }}>Clear</button>
                </div>
              </div>
              <div className="field is-grouped rating-range">
                <div className="control">
                  <input
                    className="input is-small rating-input"
                    type="number"
                    value={ratingStart}
                    placeholder="Minimum rating"
                    onChange={(e) => {
                      setRatingStart(e.target.value);
                      debouncedOnChange('rating_start', e.target.value);
                    }}
                  />
                </div>
                <span className="rating-range-separator">-</span>
                <div className="control">
                  <input
                    className="input is-small rating-input"
                    type="number"
                    value={ratingEnd}
                    placeholder="Maximum rating"
                    onChange={(e) => {
                      setRatingEnd(e.target.value);
                      debouncedOnChange('rating_end', e.target.value);
                    }}
                  />
                </div>
                <div className="control">
                  <button className="button is-small is-light" onClick={() => {
                    setRatingStart('');
                    setRatingEnd('');
                    onClearProps(['rating_start', 'rating_end']);
                  }}>Clear</button>
                </div>
              </div>
            </Section>
            <Section title="Event"
                     isOpen={openFilters.event}
                     setIsOpen={(isOpen: boolean) => setOpenFilters({ ...openFilters, event: isOpen })}
                     isBold={
                        !!filters.event_name ||
                        !!filters.date_start ||
                        !!filters.date_end
                     }>
              <div className="field is-grouped">
                <div className="control is-expanded">
                  <Autosuggest suggestions={eventSuggestions}
                               onSuggestionsFetchRequested={debouncedGetEventSuggestions}
                               onSuggestionsClearRequested={() => setEventSuggestions([])}
                               multiSection={false}
                               getSuggestionValue={(suggestion) => suggestion}
                               renderSuggestion={(suggestion) => suggestion}
                               inputProps={{
                                 className: "input is-small",
                                 value: eventName,
                                 placeholder: "Event Name",
                                 onChange: (_: any, { newValue }) => {
                                   setEventName(newValue);
                                   debouncedOnChange('event_name', newValue);
                                 }
                               }} />
                </div>
                <div className="control">
                  <button className="button is-small is-light" onClick={() => {
                    setEventName('');
                    onClearProps(['event_name']);
                  }}>Clear</button>
                </div>
              </div>
              <div className="field is-grouped date-range">
                <div className="control">
                  <input
                    className="input is-small date-input"
                    type="date"
                    value={filters.date_start ? dayjs(filters.date_start).format('YYYY-MM-DD') : ''}
                    onChange={(e) => onChange('date_start', dayjs(e.target.value).toISOString())}
                  />
                </div>
                <span className="date-range-separator">-</span>
                <div className="control">
                  <input
                    className="input is-small date-input"
                    type="date"
                    value={filters.date_end ? dayjs(filters.date_end).format('YYYY-MM-DD') : ''}
                    onChange={(e) => onChange('date_end', dayjs(e.target.value).toISOString())}
                  />
                </div>
                <div className="control">
                  <button className="button is-small is-light" onClick={onClearProps.bind(null, ['date_start', 'date_end'])}>Clear</button>
                </div>
              </div>
            </Section>
            <Section title="Division"
                     isOpen={openFilters.division}
                     setIsOpen={(isOpen: boolean) => setOpenFilters({ ...openFilters, division: isOpen })}
                     isBold={anyDivisionFiltersSet}>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Age:</label>
                {['Adult', 'Master 1', 'Master 2', 'Master 3', 'Master 4', 'Master 5', 'Master 6', 'Master 7', 'Juvenile'].map(age => {
                  const key = ageToFilter(age);
                  return (
                    <label key={age} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {age}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearOrAll.bind(null, ['age_adult', 'age_master1', 'age_master2', 'age_master3', 'age_master4', 'age_master5', 'age_master6', 'age_master7', 'age_juvenile'])}>
                  {(filters.age_adult || filters.age_master1 || filters.age_master2 || filters.age_master3 || filters.age_master4 || filters.age_master5 || filters.age_master6 || filters.age_master7 || filters.age_juvenile) ? 'Clear' : 'All'}
                </button>
              </div>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Gender:</label>
                {['Male', 'Female'].map(gender => {
                  const key = genderToFilter(gender);
                  return (
                    <label key={gender} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {gender}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearOrAll.bind(null, ['gender_male', 'gender_female'])}>
                  {(filters.gender_male || filters.gender_female) ? 'Clear' : 'All'}
                </button>
              </div>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Belt:</label>
                {['White', 'Blue', 'Purple', 'Brown', 'Black'].map(belt => {
                  const key = beltToFilter(belt);
                  return (
                    <label key={belt} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {belt}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearOrAll.bind(null, ['belt_white', 'belt_blue', 'belt_purple', 'belt_brown', 'belt_black'])}>
                  {(filters.belt_white || filters.belt_blue || filters.belt_purple || filters.belt_brown || filters.belt_black) ? 'Clear' : 'All'}
                </button>
              </div>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Weight:</label>
                {['Rooster', 'Light Feather', 'Feather', 'Light', 'Middle',
                  'Medium Heavy', 'Heavy', 'Super Heavy', 'Ultra Heavy', 'Open Class'
                ].map(weight => {
                  const key = weightToFilter(weight);
                  return (
                    <label key={weight} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {weight}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearOrAll.bind(null, ['weight_rooster', 'weight_light_feather', 'weight_feather', 'weight_light', 'weight_middle', 'weight_medium_heavy', 'weight_heavy', 'weight_super_heavy', 'weight_ultra_heavy', 'weight_open_class'])}>
                  {(filters.weight_rooster || filters.weight_light_feather || filters.weight_feather || filters.weight_light || filters.weight_middle || filters.weight_medium_heavy || filters.weight_heavy || filters.weight_super_heavy || filters.weight_ultra_heavy || filters.weight_open_class) ? 'Clear' : 'All'}
                </button>
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

export default DBFilters;
