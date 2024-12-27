import GiTabs, { type TabName } from './GiTabs';
import EloTable from './EloTable';
import { FilterValues } from './DBFilters';

interface RatingsProps {
  activeTab: TabName;
  setActiveTab: (activeTab: TabName) => void;
  setFilters: (filters: FilterValues) => void;
}

function Ratings(props: RatingsProps) {
  return (
    <div className="container">
      <GiTabs setActiveTab={props.setActiveTab} activeTab={props.activeTab} />
      <EloTable gi={props.activeTab === 'Gi'} setFilters={props.setFilters} />
    </div>
  )
}

export default Ratings;
