import { useState, useRef } from 'react';
import { FilterKeys, DivisionFilterKeys, weightToFilter } from './filterTypes';
import useClickOutside from '../../hooks/useClickOutside';

interface WeightFilterProps {
  filters: any;
  onClearOrAll: (propnames: DivisionFilterKeys[]) => void;
  onChange: (key: FilterKeys, value: any) => void;
}

function WeightFilter({ filters, onClearOrAll, onChange }: WeightFilterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  
  const weights = ['Rooster', 'Light Feather', 'Feather', 'Light', 'Middle', 'Medium Heavy', 'Heavy', 'Super Heavy', 'Ultra Heavy', 'Open Class'];
  const weightKeys: DivisionFilterKeys[] = ['weight_rooster', 'weight_light_feather', 'weight_feather', 'weight_light', 'weight_middle', 'weight_medium_heavy', 'weight_heavy', 'weight_super_heavy', 'weight_ultra_heavy', 'weight_open_class'];

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
            aria-controls="weight-dropdown-menu"
            onClick={() => setIsOpen(!isOpen)}
            style={{ minWidth: '140px' }}
          >
            <span>Weight {getSelectedCount(weights, weightToFilter) > 0 ? `(${getSelectedCount(weights, weightToFilter)})` : ''}</span>
            <span className="icon is-small">
              <i className="fas fa-angle-down" aria-hidden="true"></i>
            </span>
          </button>
        </div>
        <div className="dropdown-menu" id="weight-dropdown-menu" role="menu">
          <div className="dropdown-content">
            {weights.map(weight => {
              const key = weightToFilter(weight);
              return (
                <a 
                  key={weight} 
                  className={`dropdown-item ${filters[key] ? 'is-active' : ''}`}
                  onClick={() => handleOptionToggle(weight, weightToFilter)}
                >
                  {weight}
                </a>
              );
            })}
            <hr className="dropdown-divider" />
            <a 
              className="dropdown-item"
              onClick={() => onClearOrAll(weightKeys)}
            >
              {hasAnySelected(weightKeys) ? 'Clear All' : 'Select All'}
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}

export default WeightFilter; 