import {useState} from 'react';
import GiTabs from './GiTabs';
import DBTable from './DBTable';

function Database() {
  const [activeTab, setActiveTab] = useState('Gi')
  return (
    <div className="container">
      <GiTabs setActiveTab={setActiveTab} activeTab={activeTab} />
      <DBTable gi={activeTab === 'Gi'} />
    </div>
  )
}

export default Database;
