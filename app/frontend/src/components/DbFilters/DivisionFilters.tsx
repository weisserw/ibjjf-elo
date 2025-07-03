import { FilterKeys, DivisionFilterKeys } from './filterTypes';
import AgeFilter from './AgeFilter';
import GenderFilter from './GenderFilter';
import BeltFilter from './BeltFilter';
import WeightFilter from './WeightFilter';

interface DivisionFiltersProps {
  filters: any;
  onClearOrAll: (propnames: DivisionFilterKeys[]) => void;
  onChange: (key: FilterKeys, value: any) => void;
}

function DivisionFilters({ filters, onClearOrAll, onChange }: DivisionFiltersProps) {
  return (
    <div className="db-filters-content w-full pt-4">
      <div className="columns is-mobile is-multiline pb-3">
        <AgeFilter 
          filters={filters}
          onClearOrAll={onClearOrAll}
          onChange={onChange}
        />
        <GenderFilter 
          filters={filters}
          onClearOrAll={onClearOrAll}
          onChange={onChange}
        />
        <BeltFilter 
          filters={filters}
          onClearOrAll={onClearOrAll}
          onChange={onChange}
        />
        <WeightFilter 
          filters={filters}
          onClearOrAll={onClearOrAll}
          onChange={onChange}
        />
      </div>
    </div>
  );
}

export default DivisionFilters; 