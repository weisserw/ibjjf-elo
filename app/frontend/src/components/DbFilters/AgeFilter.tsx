import { useState, useRef } from 'react';
import { FilterKeys, DivisionFilterKeys, ageToFilter } from './filterTypes';
import useClickOutside from '../../hooks/useClickOutside';

interface AgeFilterProps {
  filters: any;
  onClearOrAll: (propnames: DivisionFilterKeys[]) => void;
  onChange: (key: FilterKeys, value: any) => void;
}

function AgeFilter({ filters, onClearOrAll, onChange }: AgeFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  const ages = ['Adult', 'Master 1', 'Master 2', 'Master 3', 'Master 4', 'Master 5', 'Master 6', 'Master 7', 'Juvenile', 'Teen'];
  const ageKeys: DivisionFilterKeys[] = ['age_adult', 'age_master1', 'age_master2', 'age_master3', 'age_master4', 'age_master5', 'age_master6', 'age_master7', 'age_juvenile', 'age_teen'];

  useClickOutside({
    ref: dropdownRef,
    callback: () => setIsOpen(false),
    enabled: isOpen
  });

  const hasAnySelected = (keys: DivisionFilterKeys[]) => keys.some(key => filters[key]);

  const getSelectedCount = (options: string[], keyFunction: (option: string) => string) => {
    return options.filter(option => {
      const key = keyFunction(option);
      return !!filters[key];
    }).length;
  };

  const handleOptionToggle = (option: string, keyFunction: (option: string) => string) => {
    const key = keyFunction(option);
    onChange(key as FilterKeys, !filters[key]);
  };

  return (
    <div className="column is-full-mobile">
      <div ref={dropdownRef} className={`dropdown w-full ${isOpen ? 'is-active' : ''}`}>
        <div className="dropdown-trigger w-full">
          <button 
            className="button is-small is-light w-full" 
            aria-haspopup="true" 
            aria-controls="age-dropdown-menu"
            onClick={() => setIsOpen(!isOpen)}
            style={{ minWidth: '140px' }}
          >
            <span>Age {getSelectedCount(ages, ageToFilter) > 0 ? `(${getSelectedCount(ages, ageToFilter)})` : ''}</span>
            <span className="icon is-small">
              <i className="fas fa-angle-down" aria-hidden="true"></i>
            </span>
          </button>
        </div>
        <div className="dropdown-menu" id="age-dropdown-menu" role="menu">
          <div className="dropdown-content">
            {ages.map(age => {
              const key = ageToFilter(age);
              return (
                <a 
                  key={age} 
                  className={`dropdown-item ${filters[key] ? 'is-active' : ''}`}
                  onClick={() => handleOptionToggle(age, ageToFilter)}
                >
                  {age}
                </a>
              );
            })}
            <hr className="dropdown-divider" />
            <a 
              className="dropdown-item"
              onClick={() => onClearOrAll(ageKeys)}
            >
              {hasAnySelected(ageKeys) ? 'Clear All' : 'Select All'}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

export default AgeFilter; 