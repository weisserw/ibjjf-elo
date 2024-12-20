import './App.css';
import Navbar from './components/Navbar';
import EloTable from './components/EloTable';
import Sidebar from './components/Sidebar';

function App() {
  return (
    <>
      <header className="hero is-small is-bold">
        <div className="hero-body">
          <Navbar />
        </div>
      </header>
      <div className="container">
        <div className="columns">
          <div className="column is-two-thirds">
            <div className="tabs">
              <ul>
                <li className="is-active"><a>Gi</a></li>
                <li><a>No Gi</a></li>
              </ul>
            </div>
            <EloTable />
          </div>
          <div className="column">
            <Sidebar />
          </div>
        </div>
      </div>
    </>
  )
}

export default App;
