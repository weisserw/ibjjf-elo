import { useState } from 'react';
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Ratings from './components/Ratings';
import Database from './components/Database';
import About from './components/About';
import NotFound from './components/NotFound';
import type { FilterValues, OpenFilters } from './components/DBFilters';
import type { TabName } from './components/GiTabs';

function App() {
  const [filters, setFilters] = useState<FilterValues>({});
  const [openFilters, setOpenFilters] = useState<OpenFilters>({athlete: true, event: false, division: false});
  const [activeTab, setActiveTab] = useState<TabName>('Gi')

  return (
    <Router>
      <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
        <header className="hero is-small is-bold">
          <div className="hero-body">
            <Navbar />
          </div>
        </header>
        <main style={{ flex: '1' }}>
          <Routes>
            <Route path="/" element={<Ratings setFilters={setFilters} setOpenFilters={setOpenFilters} activeTab={activeTab} setActiveTab={setActiveTab} />} />
            <Route path="/database" element={<Database filters={filters}
                                                       setFilters={setFilters}
                                                       openFilters={openFilters}
                                                       setOpenFilters={setOpenFilters}
                                                       activeTab={activeTab}
                                                       setActiveTab={setActiveTab} />} />
            <Route path="/about" element={<About />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </main>
        <footer className="footer" style={{ fontSize: '0.75rem', textAlign: 'right', padding: '0.5rem 1rem' }}>
          <div className="content">
            <p>© 2024 IBJJJFRankings.com</p>
          </div>
        </footer>
      </div>
    </Router>
  );
}

export default App;
