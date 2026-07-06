import { useEffect, useState } from 'react';
import axios from 'axios';
import { t, type translationKeys } from '../translate';

import './MatchDetailView.css';

type ParticipantKey = 'red' | 'blue';
type ScoreCategory = 'points' | 'advantages' | 'penalties';

interface MatchDetailParticipant {
  key: ParticipantKey;
  name: string;
  fullName: string;
  titleName: string;
  scoreboardPosition: 'top' | 'bottom';
}

interface MatchDetailScore {
  points: number;
  advantages: number;
  penalties: number;
}

interface MatchDetailEvent {
  kind: string;
  time: string | null;
  actions?: MatchDetailAction[];
  endingMethod?: string;
  endingMethodAmount?: number | null;
  winnerKey?: ParticipantKey | null;
  athleteName?: string | null;
  totals: Record<ParticipantKey, MatchDetailScore>;
}

interface MatchDetailResponse {
  matchId: string;
  matchTime: string | null;
  participants: MatchDetailParticipant[];
  events: MatchDetailEvent[];
}

interface MatchDetailAction {
  kind: string;
  participantKey: ParticipantKey;
  athleteName: string;
  category: ScoreCategory;
  delta: number;
  verb?: string;
}

interface MatchDetailViewProps {
  matchId: string;
  showTitle?: boolean;
}

interface MatchDetailModalProps extends MatchDetailViewProps {
  onClose: () => void;
}

const categoryLabels: Record<ScoreCategory, { singular: translationKeys; plural: translationKeys }> = {
  points: { singular: "point", plural: "points" },
  advantages: { singular: "advantage", plural: "advantages" },
  penalties: { singular: "penalty", plural: "penalties" },
};

const scoreSummary = (totals: Record<ParticipantKey, MatchDetailScore>, winnerKey: ParticipantKey | null) => {
  const show = (value: number | null | undefined) => value ?? '-';
  const loserKey = winnerKey === 'red' ? 'blue' : 'red';
  const firstKey = winnerKey ?? 'red';
  const secondKey = winnerKey ? loserKey : 'blue';
  const winnerScore = totals[firstKey];
  const loserScore = totals[secondKey];

  return (
    <span className="match-detail-score-summary">
      <span className="match-detail-score-points">{show(winnerScore?.points)}-{show(loserScore?.points)}</span>
      <span className="match-detail-score-advantages">{show(winnerScore?.advantages)}-{show(loserScore?.advantages)}</span>
      <span className="match-detail-score-penalties">{show(winnerScore?.penalties)}-{show(loserScore?.penalties)}</span>
    </span>
  );
}

const participantName = (participants: MatchDetailParticipant[], key: ParticipantKey) => {
  return participants.find(participant => participant.key === key)?.name ?? key;
}

const titleName = (participants: MatchDetailParticipant[], key: ParticipantKey) => {
  return participants.find(participant => participant.key === key)?.titleName ?? participantName(participants, key);
}

const amountText = (action: MatchDetailAction) => {
  const amount = Math.abs(action.delta);
  const label = amount === 1
    ? categoryLabels[action.category].singular
    : categoryLabels[action.category].plural;
  return `${amount} ${t(label)}`;
}

const formatActionGroup = (athleteName: string, actions: MatchDetailAction[]) => {
  const scored = actions.filter(action => action.kind !== 'retraction' && action.category !== 'penalties');
  const received = actions.filter(action => action.kind !== 'retraction' && action.category === 'penalties');
  const retractions = actions.filter(action => action.kind === 'retraction');
  const phrases: string[] = [];

  if (scored.length > 0) {
    phrases.push(`${athleteName} ${t(scored[0].verb === 'awarded' ? "awarded" : "scored")} ${joinAmounts(scored)}`);
  }
  if (received.length > 0) {
    phrases.push(`${athleteName} ${t("received")} ${joinAmounts(received)}`);
  }
  retractions.forEach(action => {
    phrases.push(`${athleteName} ${t(categoryLabels[action.category].plural)} ${t("retracted on review")}`);
  });

  return phrases.join('. ');
}

const joinAmounts = (actions: MatchDetailAction[]) => {
  const amounts = actions.map(amountText);
  if (amounts.length <= 1) {
    return amounts[0] ?? '';
  }
  return `${amounts.slice(0, -1).join(', ')} ${t("and")} ${amounts[amounts.length - 1]}`;
}

const eventText = (event: MatchDetailEvent) => {
  if (event.kind === 'final') {
    const athleteName = event.athleteName ?? '';
    return `${athleteName} ${t("won by")} ${endingMethodText(event)}`;
  }

  const groups = new Map<string, MatchDetailAction[]>();
  event.actions?.forEach(action => {
    const key = `${action.participantKey}:${action.athleteName}`;
    groups.set(key, [...(groups.get(key) ?? []), action]);
  });

  return Array.from(groups.values())
    .map(actions => formatActionGroup(actions[0].athleteName, actions))
    .join('. ');
}

const endingMethodText = (event: MatchDetailEvent) => {
  const method = event.endingMethod ?? "Final";
  if (method === 'points' || method === 'advantages' || method === 'penalties') {
    const labels = categoryLabels[method];
    return t((event.endingMethodAmount === 1 ? labels.singular : labels.plural));
  }
  const translated = t(method as translationKeys);
  return method === 'DQ' ? translated : translated.toLocaleLowerCase();
}

function MatchDetailView({ matchId, showTitle = false }: MatchDetailViewProps) {
  const [detail, setDetail] = useState<MatchDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let ignore = false;
    setLoading(true);
    setError(null);
    setDetail(null);

    axios.get<MatchDetailResponse>(`/api/matches/${matchId}/detail-events`)
      .then(response => {
        if (!ignore) {
          setDetail(response.data);
        }
      })
      .catch(() => {
        if (!ignore) {
          setError('Unable to load match details');
        }
      })
      .finally(() => {
        if (!ignore) {
          setLoading(false);
        }
      });

    return () => {
      ignore = true;
    };
  }, [matchId]);

  if (loading) {
    return <div className="match-detail-status">{t("Loading match details")}</div>;
  }

  if (error) {
    return <div className="match-detail-status has-text-danger">{t(error as translationKeys)}</div>;
  }

  if (!detail || detail.events.length === 0) {
    return <div className="match-detail-status">{t("No match details available")}</div>;
  }

  const winnerKey = detail.events.find(event => event.kind === 'final')?.winnerKey ?? null;

  return (
    <div className="match-detail-view">
      {showTitle && (
        <h3 className="title is-5 match-detail-title">
          {titleName(detail.participants, 'red')} vs {titleName(detail.participants, 'blue')}
        </h3>
      )}
      <div className="match-detail-match-time">
        <strong>{t("Match time")}:</strong> {detail.matchTime ?? '-'}
      </div>
      <table className="table is-fullwidth is-narrow match-detail-table">
        <thead>
          <tr>
            <th>{t("Time")}</th>
            <th>{t("Event")}</th>
            <th>{t("Score")}</th>
          </tr>
        </thead>
        <tbody>
          {detail.events.map((event, index) => (
            <tr key={`${event.kind}-${index}`}>
              <td className="match-detail-time">{event.time ?? '-'}</td>
              <td>{eventText(event)}</td>
              <td className="match-detail-score">{scoreSummary(event.totals, winnerKey)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function MatchDetailModal({ matchId, onClose }: MatchDetailModalProps) {
  return (
    <div className="modal is-active match-detail-modal">
      <div className="modal-background" onClick={onClose}></div>
      <div className="modal-content match-detail-modal-content">
        <button
          type="button"
          className="delete is-medium match-detail-modal-close"
          aria-label="Close match details"
          onClick={onClose}
        />
        <div className="box match-detail-modal-body">
          <MatchDetailView matchId={matchId} showTitle />
        </div>
      </div>
    </div>
  );
}

export default MatchDetailView;
