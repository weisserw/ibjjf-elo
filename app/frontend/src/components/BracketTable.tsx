import type { Competitor } from "./BracketUtils";

interface BracketTableProps {
  competitors: Competitor[] | null;
  sortColumn?: string;
  showSeed: boolean;
  columnClicked?: (column: SortColumn, ev: React.MouseEvent<HTMLAnchorElement>) => void;
  athleteClicked: (ev: React.MouseEvent<HTMLAnchorElement>, name: string) => void;
}

export type SortColumn = 'rating' | 'seed'

function BracketTable(props: BracketTableProps) {
  const { competitors, sortColumn, columnClicked, athleteClicked } = props;

  return (
    <div className="table-container">
      <table className="table is-fullwidth bracket-table">
        <thead>
          <tr>
            <th className="has-text-right">
              {
                (sortColumn !== undefined && sortColumn !== 'rating') ?
                  <a href="#" onClick={columnClicked?.bind(null, 'rating')}>#</a> :
                  <span># ↓</span>
              }
            </th>
            {
              props.showSeed &&
              <th className="has-text-right">
                {
                  (sortColumn !== undefined && sortColumn !== 'seed') ?
                    <a href="#" onClick={columnClicked?.bind(null, 'seed')}>IBJJF Seed</a> :
                    <span>IBJJF Seed ↓</span>
                }
              </th>
            }
            <th>Name</th>
            <th>Team</th>
            <th className="has-text-right">Rating</th>
            <th className="has-text-right">Rank</th>
          </tr>
        </thead>
        <tbody>
          {
            competitors?.map(competitor => (
              <tr key={competitor.name}>
                <td className="has-text-right">{competitor.ordinal}</td>
                {
                  props.showSeed &&
                  <td className="has-text-right">{competitor.seed}</td>
                }
                {
                  competitor.id !== null ?
                    <td><a href="#" onClick={e => athleteClicked(e, competitor.name)}>{competitor.name}</a></td> :
                    <td>{competitor.name}</td>
                }
                <td>{competitor.team}</td>
                <td className="has-text-right">{competitor.rating ?? ''}</td>
                <td className="has-text-right">{competitor.rank ?? ''}</td>
              </tr>
            ))
          }
        </tbody>
      </table>
    </div>
  );
}

export default BracketTable;