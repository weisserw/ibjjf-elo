import GiTabs, { type TabName } from './GiTabs';
import EloTable from './EloTable';

interface RatingsProps {
  activeTab: TabName;
  setActiveTab: (activeTab: TabName) => void;
}

function Ratings(props: RatingsProps) {
  return (
    <div className="container">
      <GiTabs setActiveTab={props.setActiveTab} activeTab={props.activeTab} />
      <EloTable gi={props.activeTab === 'Gi'} />
    </div>
  )
}

export default Ratings;
