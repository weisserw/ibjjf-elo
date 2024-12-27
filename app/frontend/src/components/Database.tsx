import GiTabs, { TabName } from './GiTabs';
import DBTable from './DBTable';
import { FilterValues } from './DBFilters';

interface DatabaseProps {
  filters: FilterValues;
  setFilters: (filters: FilterValues) => void;
  activeTab: TabName;
  setActiveTab: (activeTab: TabName) => void;
}

function Database(props: DatabaseProps) {
  return (
    <div className="container">
      <GiTabs setActiveTab={props.setActiveTab} activeTab={props.activeTab} />
      <DBTable gi={props.activeTab === 'Gi'} {...props} />
    </div>
  )
}

export default Database;
