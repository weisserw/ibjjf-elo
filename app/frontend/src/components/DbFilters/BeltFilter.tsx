import { useState, useRef } from 'react';
import { FilterKeys, DivisionFilterKeys, beltToFilter } from './filterTypes';
import useClickOutside from '../../hooks/useClickOutside';

interface BeltFilterProps {
  filters: any;
  onClearOrAll: (propnames: DivisionFilterKeys[]) => void;
  onChange: (key: FilterKeys, value: any) => void;
}

function BeltFilter({ filters, onClearOrAll, onChange }: BeltFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  const belts = ['White', 'Grey', 'Yellow', 'Orange', 'Green', 'Blue', 'Purple', 'Brown', 'Black'];
  const beltKeys: DivisionFilterKeys[] = ['belt_white', 'belt_blue', 'belt_purple', 'belt_brown', 'belt_black'];

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
            aria-controls="belt-dropdown-menu"
            onClick={() => setIsOpen(!isOpen)}
            style={{ minWidth: '140px' }}
          >
            <span>Belt {getSelectedCount(belts, beltToFilter) > 0 ? `(${getSelectedCount(belts, beltToFilter)})` : ''}</span>
            <span className="icon is-small">
              <i className="fas fa-angle-down" aria-hidden="true"></i>
            </span>
          </button>
        </div>
        <div className="dropdown-menu" id="belt-dropdown-menu" role="menu">
          <div className="dropdown-content">
            {belts.map(belt => {
              const key = beltToFilter(belt);
              return (
                <a 
                  key={belt} 
                  className={`dropdown-item ${filters[key] ? 'is-active' : ''}`}
                  onClick={() => handleOptionToggle(belt, beltToFilter)}
                >
                  {belt}
                </a>
              );
            })}
            <hr className="dropdown-divider" />
            <a 
              className="dropdown-item"
              onClick={() => onClearOrAll(beltKeys)}
            >
              {hasAnySelected(beltKeys) ? 'Clear All' : 'Select All'}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

export default BeltFilter; 