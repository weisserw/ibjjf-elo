import { useState, useCallback } from 'react'
import axios from 'axios';
import { debounce } from 'lodash';
import Autosuggest from 'react-autosuggest';
import { axiosErrorToast } from '../utils';

interface SearchEloTableProps {
  nameFilter: string;
  setNameFilter: (value: string) => void;
}

function SearchEloTable({ nameFilter, setNameFilter }: SearchEloTableProps) {
  const [nameFilterSearch, setNameFilterSearch] = useState(nameFilter)
  const [athleteSuggestions, setAthleteSuggestions] = useState<string[]>([])

  const getAthleteSuggestions = async ({ value }: { value: string }) => {
    try {
      const response = await axios.get(`/api/athletes?search=${encodeURIComponent(value)}`);
      setAthleteSuggestions(response.data);
    } catch (error) {
      axiosErrorToast(error);
    }
  }

  const debouncedGetAthleteSuggestions = useCallback(debounce(getAthleteSuggestions, 300, {trailing: true}), []);

  const debouncedSetNameFilter = useCallback(
    debounce((value: string) => setNameFilter(value), 750),
    []
  );

  const onNameFilterChange = (value: string) => {
    setNameFilterSearch(value)
    debouncedSetNameFilter(value)
  }

  return (
    <div className="field position-relative py-3">
    <div className="control has-icons-left">
      <Autosuggest suggestions={athleteSuggestions}
                    onSuggestionsFetchRequested={debouncedGetAthleteSuggestions}
                    onSuggestionsClearRequested={() => setAthleteSuggestions([])}
                    multiSection={false}
                    getSuggestionValue={(suggestion) => '"' + suggestion + '"'}
                    renderSuggestion={(suggestion) => suggestion}
                    inputProps={{
                      className: "input",
                      value: nameFilterSearch,
                      placeholder: "Search Within Division",
                      onChange: (_: any, { newValue }) => {
                      onNameFilterChange(newValue)
                      }
                    }} />
      <span className="icon is-small is-left">
        <i className="fas fa-filter"></i>
      </span>
    </div>
    {
      nameFilterSearch && (
        <span className="icon is-small clear-filter" onClick={() => {
          setNameFilterSearch('')
          setNameFilter('')
        }}>
          <i className="fas fa-times"></i>
        </span>
      )
    }
  </div>
  )
}

export default SearchEloTable 