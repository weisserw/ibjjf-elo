import {useState} from 'react';
import GiTabs from './GiTabs';
import EloTable from './EloTable';

function Ratings() {
  const [activeTab, setActiveTab] = useState('Gi')
  return (
    <div className="container">
      <GiTabs setActiveTab={setActiveTab} activeTab={activeTab} />
      <EloTable gi={activeTab === 'Gi'} />
    </div>
  )
}

export default Ratings;
