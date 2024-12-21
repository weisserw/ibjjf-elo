import {useState} from 'react';
import Navbar from './components/Navbar';
import EloTable from './components/EloTable';
import classNames from 'classnames';
import './App.css';

function App() {
  const [activeTab, setActiveTab] = useState('Gi')
  return (
    <>
      <header className="hero is-small is-bold">
        <div className="hero-body">
          <Navbar />
        </div>
      </header>
      <div className="container">
        <div className="tabs">
          <ul>
            <li onClick={() => setActiveTab('Gi')} className={classNames({"is-active": activeTab === 'Gi'})}><a>Gi</a></li>
            <li onClick={() => setActiveTab('No Gi')} className={classNames({"is-active": activeTab === 'No Gi'})}><a>No Gi</a></li>
          </ul>
        </div>
        <EloTable gi={activeTab === 'Gi'} />
      </div>
    </>
  )
}

export default App;
