import { useEffect, useState } from 'react';
import axios from 'axios';
import { Link, useParams } from 'react-router-dom';
import { axiosErrorToast, badgeForPercentile, beltColorEmojis, teamSlugFromName } from '../utils';
import { t } from '../translate';

type EliteCompetitor = {
  athlete_slug: string | null;
  athlete_name: string;
  personal_name: string | null;
  percentile: number;
  rating: number | null;
  belt: string | null;
  current_team: string | null;
};

type TeamResponse = {
  team_name: string;
  elite_competitors: EliteCompetitor[];
};

function Team() {
  const { slug } = useParams<{ slug: string }>();
  const [teamData, setTeamData] = useState<TeamResponse | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!slug) {
      return;
    }

    setLoading(true);
    axios
      .get<TeamResponse>(`/api/teams/${encodeURIComponent(slug)}`)
      .then(response => {
        setTeamData(response.data);
      })
      .catch(error => {
        axiosErrorToast(error);
        setTeamData(null);
      })
      .finally(() => {
        setLoading(false);
      });
  }, [slug]);

  return (
    <div className="container pl-2 pr-2">
      <div className="box mt-4">
        <h1 className="title is-4 mb-2">
          {teamData?.team_name ? teamData.team_name : (loading ? <span className="loader" /> : '')}
        </h1>
        <p className="subtitle is-6 mt-0 mb-4">{t('Elite adult athletes who have represented or currently represent this team:')}</p>

        {!loading && teamData && teamData.elite_competitors.length === 0 && (
          <div className="notification">{t('No elite competitors found for this team.')}</div>
        )}

        {!loading && teamData && teamData.elite_competitors.length > 0 && (
          <table className="table is-fullwidth is-striped">
            <thead>
              <tr>
                <th>{t('Athlete')}</th>
                <th className="has-text-centered">{t('Belt')}</th>
                <th>{t('Current Team')}</th>
                <th className="has-text-right">{t('Rating')}</th>
              </tr>
            </thead>
            <tbody>
              {teamData.elite_competitors.map((competitor, index) => (
                <tr key={`${competitor.athlete_slug || competitor.athlete_name}-${index}`}>
                  <td>
                    {(() => {
                      const [badge, badgeDescription] = badgeForPercentile(
                        competitor.percentile,
                        competitor.belt || '',
                        'Adult',
                      );
                      const athleteName = competitor.personal_name || competitor.athlete_name;
                      const content = (
                        <>
                          {badge && (
                            <img
                              src={badge}
                              alt={badgeDescription}
                              title={badgeDescription}
                              width={24}
                              height={24}
                              style={{ marginRight: 10, verticalAlign: 'middle' }}
                            />
                          )}
                          <span>{athleteName}</span>
                        </>
                      );

                      if (competitor.athlete_slug) {
                        return (
                          <Link to={`/athlete/${encodeURIComponent(competitor.athlete_slug)}`}>
                            {content}
                          </Link>
                        );
                      }

                      return content;
                    })()}
                  </td>
                  <td className="has-text-centered">{(competitor.belt && (beltColorEmojis[competitor.belt] || beltColorEmojis[competitor.belt.replace('-', '_')])) || '-'}</td>
                  <td>
                    {(() => {
                      if (!competitor.current_team) {
                        return '-';
                      }

                      const isCurrentTeam =
                        !!teamData?.team_name &&
                        competitor.current_team.trim() === teamData.team_name.trim();
                      if (isCurrentTeam) {
                        return competitor.current_team;
                      }

                      return (
                        <Link to={`/team/${teamSlugFromName(competitor.current_team)}`}>
                          {competitor.current_team}
                        </Link>
                      );
                    })()}
                  </td>
                  <td className="has-text-right">{competitor.rating === null ? '-' : Math.round(competitor.rating)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

export default Team;
