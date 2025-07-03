import { useState, useRef } from 'react';
import { FilterKeys, DivisionFilterKeys, genderToFilter } from './filterTypes';
import useClickOutside from '../../hooks/useClickOutside';

interface GenderFilterProps {
  filters: any;
  onClearOrAll: (propnames: DivisionFilterKeys[]) => void;
  onChange: (key: FilterKeys, value: any) => void;
}

function GenderFilter({ filters, onClearOrAll, onChange }: GenderFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  const genders = ['Male', 'Female'];
  const genderKeys: DivisionFilterKeys[] = ['gender_male', 'gender_female'];

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
            aria-controls="gender-dropdown-menu"
            onClick={() => setIsOpen(!isOpen)}
            style={{ minWidth: '140px' }}
          >
            <span>Gender {getSelectedCount(genders, genderToFilter) > 0 ? `(${getSelectedCount(genders, genderToFilter)})` : ''}</span>
            <span className="icon is-small">
              <i className="fas fa-angle-down" aria-hidden="true"></i>
            </span>
          </button>
        </div>
        <div className="dropdown-menu" id="gender-dropdown-menu" role="menu">
          <div className="dropdown-content">
            {genders.map(gender => {
              const key = genderToFilter(gender);
              return (
                <a 
                  key={gender} 
                  className={`dropdown-item ${filters[key] ? 'is-active' : ''}`}
                  onClick={() => handleOptionToggle(gender, genderToFilter)}
                >
                  {gender}
                </a>
              );
            })}
            <hr className="dropdown-divider" />
            <a 
              className="dropdown-item"
              onClick={() => onClearOrAll(genderKeys)}
            >
              {hasAnySelected(genderKeys) ? 'Clear All' : 'Select All'}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

export default GenderFilter; 