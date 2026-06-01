import { Link } from 'react-router-dom'
import { t } from '../translate'
import { teamSlugFromName } from '../utils'

type YearlyTeamAward = {
  place: number
  team: string
  wins: number
  winRatio: number
  averageDefeatedRating: number
  score: number
}

const awards: YearlyTeamAward[] = [
  { place: 1, team: 'AOJ', wins: 362, winRatio: 73.6, averageDefeatedRating: 1791, score: 1318 },
  { place: 2, team: 'Soldiers Jiu-Jitsu', wins: 179, winRatio: 67.3, averageDefeatedRating: 1788, score: 1203 },
  { place: 3, team: 'DreamArt', wins: 315, winRatio: 67.5, averageDefeatedRating: 1679, score: 1133 },
  { place: 4, team: 'Atos Jiu-Jitsu', wins: 442, winRatio: 64.3, averageDefeatedRating: 1709, score: 1099 },
  { place: 5, team: 'Marcio Andre Jiu-Jitsu', wins: 150, winRatio: 64.1, averageDefeatedRating: 1700, score: 1090 },
  { place: 6, team: 'Team Lloyd Irvin', wins: 72, winRatio: 58.5, averageDefeatedRating: 1694, score: 992 },
  { place: 7, team: 'Start Doing', wins: 148, winRatio: 63.2, averageDefeatedRating: 1550, score: 981 },
  { place: 8, team: 'Alliance', wins: 1065, winRatio: 58.3, averageDefeatedRating: 1669, score: 973 },
  { place: 9, team: 'Nxtgen Jiu-Jitsu', wins: 72, winRatio: 60.5, averageDefeatedRating: 1608, score: 973 },
  { place: 10, team: 'Six Blades Jiu-Jitsu', wins: 208, winRatio: 55.2, averageDefeatedRating: 1740, score: 960 },
]

function YearlyTeamAwards() {
  return (
    <div className="container pl-2 pr-2">
      <h1 className="title is-4 mt-6 mb-4">Yearly Team Awards - 2026 Gi</h1>
      <p className="mb-4">
        {t('The yearly team awards use the same criteria as our ')}
        <Link to="/teams">{t('per-event awards')}</Link>
        {t(', but from a combination of the four "Grand Slam" events (Euros, Pans, Brasileiros and Worlds). Teams must have at least 15 participants in two of the four events to qualify.')}
      </p>
      <div className="table-container">
        <table className="table is-fullwidth bracket-table">
          <thead>
            <tr>
              <th className="has-text-centered">Place</th>
              <th>Team</th>
              <th className="has-text-right">Wins</th>
              <th className="has-text-right">Win Ratio</th>
              <th className="has-text-right">Average Defeated Rating</th>
              <th className="has-text-right">Score</th>
            </tr>
          </thead>
          <tbody>
            {awards.map((award) => (
              <tr key={award.place}>
                <td className="has-text-centered">{award.place}</td>
                <td>
                  <Link to={`/team/${teamSlugFromName(award.team)}`}>
                    {award.team}
                  </Link>
                </td>
                <td className="has-text-right">{award.wins}</td>
                <td className="has-text-right">{award.winRatio.toFixed(1)}%</td>
                <td className="has-text-right">{award.averageDefeatedRating}</td>
                <td className="has-text-right">{award.score}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

export default YearlyTeamAwards
