import { useState, useEffect, useCallback } from 'react';
import debounce from 'lodash/debounce';
import { useAppContext } from '../../AppContext';
import Menu from '../Menu';
import AthleteFilters from './AthleteFilters';
import EventFilters from './EventFilters';
import DivisionFilters from './DivisionFilters';
import { FilterKeys, DivisionFilterKeys } from './filterTypes';

import './DBFilters.css';

function DBFilters() {
  const {
    filters,
    setFilters,
    activeTab,
  } = useAppContext();

  const gi = activeTab === 'Gi';

  const [eventName, setEventName] = useState(filters.event_name || '');

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

  const debouncedOnChange = useCallback(debounce(onChange, 750, { trailing: true }), [filters]);

  useEffect(() => {
    if (filters.event_name !== eventName) {
      setEventName(filters.event_name || '');
    }
  }, [filters.event_name]);

  const filtersContent = (
    <>
    <AthleteFilters filters={filters} setFilters={setFilters} onClearProps={onClearProps} debouncedOnChange={debouncedOnChange} />
    <EventFilters filters={filters} setFilters={setFilters} onClearProps={onClearProps} debouncedOnChange={debouncedOnChange} gi={gi} />
    <DivisionFilters filters={filters} onClearOrAll={onClearOrAll} onChange={onChange} />
    </>
  );

  return (  
    <>
    <Menu wrapperClassName="is-hidden-tablet" menuButton={{ label: 'Filter' }} content={filtersContent} />
    <div className="elo-filters-inline-row is-hidden-mobile">
      {filtersContent}
    </div>
    </>
  );
}

export default DBFilters;
