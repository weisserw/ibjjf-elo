import GiTabs, { type TabName } from './GiTabs';
import EloTable from './EloTable';
import type { FilterValues, OpenFilters } from './DBFilters';

interface RatingsProps {
  activeTab: TabName;
  setActiveTab: (activeTab: TabName) => void;
  setFilters: (filters: FilterValues) => void;
  setOpenFilters: (openFilters: OpenFilters) => void;
}

function Ratings(props: RatingsProps) {
  return (
    <div className="container">
      <GiTabs setActiveTab={props.setActiveTab} activeTab={props.activeTab} />
      <EloTable gi={props.activeTab === 'Gi'} setFilters={props.setFilters} setOpenFilters={props.setOpenFilters} />
    </div>
  )
}

export default Ratings;
