import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Link, Navigate, useLocation } from 'react-router-dom';
import Navbar from './components/Navbar';
import Ratings from './components/Ratings';
import Database from './components/Database';
import Brackets from './components/Brackets';
import Awards from './components/Awards';
import Calculator from './components/Calculator';
import Athlete from './components/Athlete';
import About from './components/About';
import News from './components/News';
import NewsItem from './components/NewsItem';
import NotFound from './components/NotFound';
import { AppProvider, useAppContext } from './AppContext';
import { t } from './translate';

function ScrollToHash() {
  const location = useLocation();

  useEffect(() => {
    if (!location.hash) {
      return;
    }

    const hashId = location.hash.slice(1);
    let attempts = 0;
    const maxAttempts = 10;

    const scrollToAnchor = () => {
      const element = document.getElementById(hashId);
      if (element) {
        element.scrollIntoView({ behavior: 'smooth', block: 'start' });
        return;
      }

      attempts += 1;
      if (attempts < maxAttempts) {
        window.setTimeout(scrollToAnchor, 50);
      }
    };

    scrollToAnchor();
  }, [location.pathname, location.hash]);

  return null;
}

function AppShell() {
  useAppContext();
  const location = useLocation();
  const showDisclaimer = location.pathname !== '/about';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      <header className="hero is-small is-bold">
        <div className="hero-body">
          <Navbar />
        </div>
      </header>
      {showDisclaimer && (
        <p className="site-disclaimer">
          {t("This site is not affiliated, endorsed by, or associated with the International Brazilian Jiu-Jitsu Federation.")}{` `}
          <Link to="/about#disclaimer">{t("More Info")}</Link>
        </p>
      )}
      <main style={{ flex: '1' }}>
        <Routes>
          <Route path="/" element={<Ratings />} />
          <Route path="/database" element={<Database />} />
          <Route path="/tournaments" element={<Brackets tab="Live" />} />
          <Route path="/tournaments/registrations" element={<Brackets tab="Registrations" />} />
          <Route path="/tournaments/archive" element={<Brackets tab="Archive" />} />
          <Route path="/tournaments/awards" element={<Navigate to="/awards" replace />} />
          <Route
            path="/awards"
            element={
              <div className="container pl-2 pr-2">
                <p>
                  {t("Search for a past event in our database to view our team rankings based on match outcomes and opponent rating. To encourage competitive participation without pressure, white belts and teens are not included in team rankings.")}
                </p>
                <Awards />
              </div>
            }
          />
          <Route path="/calculator" element={<Calculator />} />
          <Route path="/news" element={<News />} />
          <Route path="/news/:id/:slug" element={<NewsItem />} />
          <Route path="/about" element={<About />} />
          <Route path="/athlete/:id" element={<Athlete />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer" style={{ fontSize: '0.75rem', textAlign: 'right', padding: '0.5rem 1rem' }}>
        <div className="content">
          <p>© 2026 JiuJitsu.net</p>
        </div>
      </footer>
    </div>
  );
}

function App() {
  return (
    <AppProvider>
      <Router>
        <ScrollToHash />
        <AppShell />
      </Router>
    </AppProvider>
  );
}

export default App;
