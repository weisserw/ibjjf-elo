import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { AppProvider } from './AppContext';
import Athlete from './components/Athlete';
import { BracketTreeMatch } from './components/BracketTree';
import type { Match } from './components/BracketUtils';
import './global.css';

const ATHLETE_ID = '11111111-1111-4111-8111-111111111111';

const bracketMatch = {
  id: '33333333-3333-4333-8333-333333333333',
  when: '2026-06-07',
  where: 'Mat 3',
  fight_num: 12,
  red_id: ATHLETE_ID,
  red_name: 'Gabi Pessanha',
  red_personal_name: null,
  red_team: 'Infight Jiu-Jitsu',
  red_country: 'BR',
  red_instagram_profile: 'gabipessanha',
  red_rating: 1842,
  red_expected: null,
  red_handicap: 0,
  red_percentile: 0.01,
  red_percentile_age: 'Adult',
  red_match_count: 80,
  red_loser: false,
  red_bye: false,
  red_note: null,
  redScoreboardPosition: 'top',
  blue_id: '22222222-2222-4222-8222-222222222222',
  blue_name: 'Maria da Silva',
  blue_personal_name: null,
  blue_team: 'Alliance',
  blue_country: null,
  blue_instagram_profile: null,
  blue_rating: 1731,
  blue_expected: null,
  blue_handicap: 0,
  blue_percentile: null,
  blue_percentile_age: null,
  blue_match_count: 60,
  blue_loser: true,
  blue_bye: false,
  blue_note: null,
  blueScoreboardPosition: 'bottom',
  finalTopPoints: 2,
  finalTopAdvantages: 0,
  finalTopPenalties: 0,
  finalBottomPoints: 0,
  finalBottomAdvantages: null,
  finalBottomPenalties: 10,
  finalMatchTimeSeconds: 172,
  video_link: null,
} as Match;

function ReferenceApp() {
  const card = new URLSearchParams(window.location.search).get('card');
  if (card === 'bracket') {
    return (
      <main className="section" data-reference="bracket">
        <div style={{ width: 360 }}>
          <BracketTreeMatch
            match={bracketMatch}
            belt="Black"
            showSeed={false}
            levelIndex={0}
            matchIndex={0}
            showRatings
            calculateEnabled={() => false}
            calculateClicked={() => undefined}
          />
        </div>
      </main>
    );
  }
  return (
    <main data-reference="athlete">
      <MemoryRouter initialEntries={[`/athlete/${ATHLETE_ID}`]}>
        <Routes>
          <Route path="/athlete/:id" element={<Athlete />} />
        </Routes>
      </MemoryRouter>
    </main>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppProvider>
      <ReferenceApp />
    </AppProvider>
  </StrictMode>,
);
