import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Navbar from './components/Navbar';
import Ratings from './components/Ratings';
import Database from './components/Database';
import About from './components/About';
import NotFound from './components/NotFound';

function App() {
  return (
    <Router>
      <header className="hero is-small is-bold">
        <div className="hero-body">
          <Navbar />
        </div>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<Ratings />} />
          <Route path="/database" element={<Database />} />
          <Route path="/about" element={<About />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
    </Router>
  );
}

export default App;
