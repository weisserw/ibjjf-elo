import { useState, ReactNode } from 'react';
import debounce from 'lodash/debounce';
import classNames from 'classnames';
import dayjs from 'dayjs';
import './DBFilters.css';

interface SectionProps {
  title: string;
  isOpen: boolean;
  setIsOpen(isOpen: boolean): void;
  children?: ReactNode;
}

function Section(props: SectionProps) {
  return (
    <div className="accordion-section">
      <h5 className="section-title" onClick={() => props.setIsOpen(!props.isOpen)}>
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
  age_juvenile1?: boolean;
  age_juvenile2?: boolean;
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

type FilterKeys = keyof FilterValues;

interface DBFiltersProps {
  filters: FilterValues;
  setFilters(filters: FilterValues): void;
}

function DBFilters(props: DBFiltersProps) {
  const [isOpen, setIsOpen] = useState(true);
  const [isAthleteOpen, setIsAthleteOpen] = useState(true);
  const [isEventOpen, setIsEventOpen] = useState(false);
  const [isDivisionOpen, setIsDivisionOpen] = useState(false);
  const [athleteName, setAthleteName] = useState(props.filters.athlete_name || '');
  const [eventName, setEventName] = useState(props.filters.event_name || '');
  const [ratingStart, setRatingStart] = useState(props.filters.rating_start || '');
  const [ratingEnd, setRatingEnd] = useState(props.filters.rating_end || '');

  const toggleAccordion = () => {
    setIsOpen(!isOpen);
  };

  const onClearProps = (propnames: FilterKeys[]) => {
    const newFilters = { ...props.filters };
    for (const prop of propnames) {
      delete newFilters[prop];
    }
    props.setFilters(newFilters);
  }

  const onChange = (key: FilterKeys, value: any) => {
    const newFilters = { ...props.filters, [key]: value };
    if (value === '' || value === false) {
      delete newFilters[key];
    }
    props.setFilters(newFilters);
  }

  const debouncedOnChange = debounce(onChange, 750);

  return (
    <div className={classNames("box accordion-box", {"open": isOpen})}>
      <div className="accordion">
        <header className="accordion-header" onClick={toggleAccordion}>
          <p>Filters</p>
          <span className={`accordion-icon ${isOpen ? 'is-active' : ''}`}>
            <i className={`fas fa-angle-${isOpen ? 'up' : 'down'}`}></i>
          </span>
        </header>
        {isOpen && (
          <div className="accordion-body">
            <Section title="Athlete" isOpen={isAthleteOpen} setIsOpen={setIsAthleteOpen}>
              <div className="field is-grouped">
                <div className="control has-icons-left is-expanded">
                  <input
                    className="input is-small"
                    type="text"
                    value={athleteName}
                    placeholder="Athlete Name"
                    onChange={(e) => {
                      setAthleteName(e.target.value);
                      debouncedOnChange('athlete_name', e.target.value);
                    }}
                  />
                  <span className="icon is-small is-left">
                    <i className="fas fa-filter"></i>
                  </span>
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
            <Section title="Event" isOpen={isEventOpen} setIsOpen={setIsEventOpen}>
              <div className="field is-grouped">
                <div className="control has-icons-left is-expanded">
                  <input
                    className="input is-small"
                    type="text"
                    placeholder="Event Name"
                    value={eventName}
                    onChange={(e) => {
                      setEventName(e.target.value);
                      debouncedOnChange('event_name', e.target.value);
                    }}
                  />
                  <span className="icon is-small is-left">
                    <i className="fas fa-filter"></i>
                  </span>
                </div>
                <div className="control">
                  <button className="button is-small is-light" onClick={() => {
                    setEventName('');
                    onClearProps(['event_name']);
                  }}>Clear</button>
                </div>
              </div>
              <div className="field is-grouped date-range">
                <div className="control has-icons-left">
                  <input
                    className="input is-small date-input"
                    type="date"
                    value={props.filters.date_start ? dayjs(props.filters.date_start).format('YYYY-MM-DD') : ''}
                    onChange={(e) => onChange('date_start', dayjs(e.target.value).toISOString())}
                  />
                  <span className="icon is-small is-left">
                    <i className="fas fa-calendar"></i>
                  </span>
                </div>
                <span className="date-range-separator">-</span>
                <div className="control has-icons-left">
                  <input
                    className="input is-small date-input"
                    type="date"
                    value={props.filters.date_end ? dayjs(props.filters.date_end).format('YYYY-MM-DD') : ''}
                    onChange={(e) => onChange('date_end', dayjs(e.target.value).toISOString())}
                  />
                  <span className="icon is-small is-left">
                    <i className="fas fa-calendar"></i>
                  </span>
                </div>
                <div className="control">
                  <button className="button is-small is-light" onClick={onClearProps.bind(null, ['date_start', 'date_end'])}>Clear</button>
                </div>
              </div>
            </Section>
            <Section title="Division" isOpen={isDivisionOpen} setIsOpen={setIsDivisionOpen}>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Gender:</label>
                {['Male', 'Female'].map(gender => {
                  const key = `gender_${gender.toLowerCase()}` as FilterKeys;
                  return (
                    <label key={gender} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!props.filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {gender}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearProps.bind(null, ['gender_male', 'gender_female'])}>Clear</button>
              </div>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Age:</label>
                {['Adult', 'Master 1', 'Master 2', 'Master 3', 'Master 4', 'Master 5', 'Master 6', 'Master 7', 'Juvenile 1', 'Juvenile 2'].map(age => {
                  const key = `age_${age.toLowerCase().replace(' ', '')}` as FilterKeys;
                  return (
                    <label key={age} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!props.filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {age}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearProps.bind(null, ['age_adult', 'age_master1', 'age_master2', 'age_master3', 'age_master4', 'age_master5', 'age_master6', 'age_master7', 'age_juvenile1', 'age_juvenile2'])}>Clear</button>
              </div>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Belt:</label>
                {['White', 'Blue', 'Purple', 'Brown', 'Black'].map(belt => {
                  const key = `belt_${belt.toLowerCase()}` as FilterKeys;
                  return (
                    <label key={belt} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!props.filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {belt}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearProps.bind(null, ['belt_white', 'belt_blue', 'belt_purple', 'belt_brown', 'belt_black'])}>Clear</button>
              </div>
              <div className="checkbox-filters checkboxes">
                <label className="filter-group-label">Weight:</label>
                {['Rooster', 'Light Feather', 'Feather', 'Light', 'Middle',
                  'Medium Heavy', 'Heavy', 'Super Heavy', 'Ultra Heavy', 'Open Class'
                ].map(weight => {
                  const key = `weight_${weight.toLowerCase().replace(' ', '_')}` as FilterKeys;
                  return (
                    <label key={weight} className="checkbox checkbox-filter">
                      <input
                        type="checkbox"
                        checked={!!props.filters[key]}
                        onChange={(e) => onChange(key, e.target.checked)}
                      />
                      {weight}
                    </label>
                  );
                })}
                <button className="button is-small is-light" onClick={onClearProps.bind(null, ['weight_rooster', 'weight_light_feather', 'weight_feather', 'weight_light', 'weight_middle', 'weight_medium_heavy', 'weight_heavy', 'weight_super_heavy', 'weight_ultra_heavy', 'weight_open_class'])}>Clear</button>
              </div>
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

export default DBFilters;
