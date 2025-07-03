import { useState, useEffect, useCallback } from 'react';
import debounce from 'lodash/debounce';
import Autosuggest from 'react-autosuggest';
import axios from 'axios';
import dayjs from 'dayjs';
import { axiosErrorToast } from '../../utils';
import { FilterKeys } from './filterTypes';

interface EventFiltersProps {
  filters: any;
  setFilters: (filters: any) => void;
  onClearProps: (propnames: FilterKeys[]) => void;
  debouncedOnChange: (key: FilterKeys, value: any) => void;
  gi: boolean;
}

function EventFilters({ filters, setFilters, onClearProps, debouncedOnChange, gi }: EventFiltersProps) {
  const [eventName, setEventName] = useState(filters.event_name || '');
  const [eventSuggestions, setEventSuggestions] = useState<string[]>([]);

  useEffect(() => {
    if (filters.event_name !== eventName) {
      setEventName(filters.event_name || '');
    }
  }, [filters.event_name]);

  const getEventSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/events?search=${encodeURIComponent(value)}&gi=${gi}`);
      setEventSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetEventSuggestions = useCallback(debounce(getEventSuggestions, 300, {trailing: true}), [gi]);

  const onChange = (key: FilterKeys, value: any) => {
    const newFilters = { ...filters, [key]: value };
    if (value === '' || value === false) {
      delete newFilters[key];
    }
    setFilters(newFilters);
  }

  return (
    <div className="db-filters-content w-full pt-4">
      <div className="columns is-mobile is-multiline">
        <div className="column is-full-mobile">
          <div className="field">
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4, justifyContent: 'space-between' }}>
              <label className="label" style={{ marginBottom: 0 }}>Event Name</label>
              <button
                className="button is-small is-light"
                style={{ marginLeft: 8 }}
                onClick={() => {
                  setEventName('');
                  onClearProps(['event_name']);
                }}
              >Clear</button>
            </div>
            <div className="control">
              <Autosuggest suggestions={eventSuggestions}
                           onSuggestionsFetchRequested={debouncedGetEventSuggestions}
                           onSuggestionsClearRequested={() => setEventSuggestions([])}
                           multiSection={false}
                           getSuggestionValue={(suggestion) => '"' + suggestion + '"'}
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
          </div>
        </div>
        <div className="column is-full-mobile">
          <div className="field">
            <div style={{ display: 'flex', alignItems: 'center', marginBottom: 4, justifyContent: 'space-between' }}>
              <label className="label" style={{ marginBottom: 0 }}>Date Range</label>
              <button
                className="button is-small is-light"
                style={{ marginLeft: 8 }}
                onClick={() => onClearProps(['date_start', 'date_end'])}
              >Clear</button>
            </div>
            <div className="field has-addons">
              <div className="control is-expanded">
                <input
                  className="input is-small date-input w-full"
                  type="date"
                  value={filters.date_start ? dayjs(filters.date_start).format('YYYY-MM-DD') : ''}
                  onChange={e => onChange('date_start', dayjs(e.target.value).toISOString())}
                />
              </div>
              <div className="px-3">-</div>
              <div className="control is-expanded">
                <input
                  className="input is-small date-input w-full"
                  type="date"
                  value={filters.date_end ? dayjs(filters.date_end).format('YYYY-MM-DD') : ''}
                  onChange={e => onChange('date_end', dayjs(e.target.value).toISOString())}
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default EventFilters; 