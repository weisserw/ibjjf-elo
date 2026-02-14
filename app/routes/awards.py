from flask import Blueprint, jsonify, request
from sqlalchemy.sql import text
from sqlalchemy import func
from extensions import db
from models import Event, Match
from normalize import normalize

awards_route = Blueprint("awards_route", __name__)


@awards_route.route("/api/awards/events/recent")
def recent_award_events():
    limit = request.args.get("limit", 10)
    try:
        limit = int(limit)
    except ValueError:
        return jsonify({"error": "Invalid limit"}), 400

    if limit < 1:
        return jsonify({"error": "Invalid limit"}), 400
    if limit > 50:
        limit = 50

    latest_matches = (
        db.session.query(
            Match.event_id.label("event_id"),
            func.max(Match.happened_at).label("latest_happened_at"),
        )
        .filter(Match.rated == True)
        .group_by(Match.event_id)
        .subquery()
    )

    events = (
        db.session.query(Event.name)
        .join(latest_matches, Event.id == latest_matches.c.event_id)
        .filter(Event.medals_only.isnot(True))
        .order_by(latest_matches.c.latest_happened_at.desc(), Event.name.asc())
        .limit(limit)
        .all()
    )

    return jsonify([event.name for event in events])


@awards_route.route("/api/awards/teams")
def teams_awards():
    event_name = request.args.get("event_name")

    if not event_name:
        return jsonify({"error": "Missing parameter"}), 400

    if event_name.startswith('"') and event_name.endswith('"'):
        event_name = event_name[1:-1]

    min_wins_required = db.session.execute(
        text(
            """
            SELECT CAST(COUNT(*) / 100.0 AS INTEGER) + 1 AS min_wins_required
            FROM matches m
            JOIN events e ON e.id = m.event_id
            WHERE e.normalized_name = :event_name
              AND m.rated = :rated
            """
        ),
        {"event_name": normalize(event_name), "rated": True},
    ).scalar()

    if min_wins_required is None:
        min_wins_required = 5
    else:
        min_wins_required = max(5, int(min_wins_required))

    results = db.session.execute(
        text(
            """
            WITH match_pairs AS (
                SELECT
                    m.id AS match_id,
                    p1.team_id AS team1_id,
                    p2.team_id AS team2_id,
                    p1.winner AS team1_winner,
                    p2.winner AS team2_winner,
                    p1.start_rating AS team1_rating,
                    p2.start_rating AS team2_rating,
                    d.weight AS division_weight,
                    d.belt AS division_belt,
                    p1.weight_for_open AS team1_weight_for_open,
                    p2.weight_for_open AS team2_weight_for_open
                FROM matches m
                JOIN events e ON e.id = m.event_id
                JOIN divisions d ON d.id = m.division_id
                JOIN match_participants p1 ON p1.match_id = m.id
                JOIN match_participants p2 ON p2.match_id = m.id
                WHERE e.normalized_name = :event_name
                  AND m.rated = :rated
                  AND p1.id < p2.id
                  AND p1.winner != p2.winner
            ),
            match_pairs_with_indices AS (
                SELECT
                    mp.*,
                    CASE mp.team1_weight_for_open
                        WHEN 'Rooster' THEN 0
                        WHEN 'Light Feather' THEN 1
                        WHEN 'Feather' THEN 2
                        WHEN 'Light' THEN 3
                        WHEN 'Middle' THEN 4
                        WHEN 'Medium Heavy' THEN 5
                        WHEN 'Heavy' THEN 6
                        WHEN 'Super Heavy' THEN 7
                        WHEN 'Ultra Heavy' THEN 8
                        ELSE NULL
                    END AS team1_weight_index,
                    CASE mp.team2_weight_for_open
                        WHEN 'Rooster' THEN 0
                        WHEN 'Light Feather' THEN 1
                        WHEN 'Feather' THEN 2
                        WHEN 'Light' THEN 3
                        WHEN 'Middle' THEN 4
                        WHEN 'Medium Heavy' THEN 5
                        WHEN 'Heavy' THEN 6
                        WHEN 'Super Heavy' THEN 7
                        WHEN 'Ultra Heavy' THEN 8
                        ELSE NULL
                    END AS team2_weight_index
                FROM match_pairs mp
            ),
            match_pairs_adjusted AS (
                SELECT
                    mpi.match_id,
                    mpi.team1_id,
                    mpi.team2_id,
                    mpi.team1_winner,
                    mpi.team2_winner,
                    mpi.team1_rating,
                    mpi.team2_rating,
                    (
                        mpi.team1_rating + CASE
                            WHEN mpi.division_weight LIKE 'Open Class%'
                                 AND mpi.team1_weight_index IS NOT NULL
                                 AND mpi.team2_weight_index IS NOT NULL
                                 AND mpi.team1_winner = 0 THEN
                                CASE
                                    WHEN mpi.team1_weight_index > mpi.team2_weight_index THEN
                                        CASE
                                            WHEN mpi.division_belt = 'BLACK' THEN
                                                CASE
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 1 THEN 54.13
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 2 THEN 64.47
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 3 THEN 132.21
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 4 THEN 168.89
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 5 THEN 176.04
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 6 THEN 224.28
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 7 THEN 372.91
                                                    ELSE 435.37
                                                END
                                            ELSE
                                                CASE
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 1 THEN 23.33
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 2 THEN 60.99
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 3 THEN 73.56
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 4 THEN 119.93
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 5 THEN 181.59
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 6 THEN 224.28
                                                    WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 7 THEN 372.91
                                                    ELSE 435.37
                                                END
                                        END
                                    WHEN mpi.team1_weight_index < mpi.team2_weight_index THEN
                                        -1 * (
                                            CASE
                                                WHEN mpi.division_belt = 'BLACK' THEN
                                                    CASE
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 1 THEN 54.13
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 2 THEN 64.47
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 3 THEN 132.21
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 4 THEN 168.89
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 5 THEN 176.04
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 6 THEN 224.28
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 7 THEN 372.91
                                                        ELSE 435.37
                                                    END
                                                ELSE
                                                    CASE
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 1 THEN 23.33
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 2 THEN 60.99
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 3 THEN 73.56
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 4 THEN 119.93
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 5 THEN 181.59
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 6 THEN 224.28
                                                        WHEN ABS(mpi.team1_weight_index - mpi.team2_weight_index) = 7 THEN 372.91
                                                        ELSE 435.37
                                                    END
                                            END
                                        )
                                    ELSE 0
                                END
                            ELSE 0
                        END
                    ) AS team1_adjusted_rating,
                    (
                        mpi.team2_rating + CASE
                            WHEN mpi.division_weight LIKE 'Open Class%'
                                 AND mpi.team1_weight_index IS NOT NULL
                                 AND mpi.team2_weight_index IS NOT NULL
                                 AND mpi.team2_winner = 0 THEN
                                CASE
                                    WHEN mpi.team2_weight_index > mpi.team1_weight_index THEN
                                        CASE
                                            WHEN mpi.division_belt = 'BLACK' THEN
                                                CASE
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 1 THEN 54.13
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 2 THEN 64.47
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 3 THEN 132.21
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 4 THEN 168.89
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 5 THEN 176.04
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 6 THEN 224.28
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 7 THEN 372.91
                                                    ELSE 435.37
                                                END
                                            ELSE
                                                CASE
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 1 THEN 23.33
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 2 THEN 60.99
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 3 THEN 73.56
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 4 THEN 119.93
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 5 THEN 181.59
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 6 THEN 224.28
                                                    WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 7 THEN 372.91
                                                    ELSE 435.37
                                                END
                                        END
                                    WHEN mpi.team2_weight_index < mpi.team1_weight_index THEN
                                        -1 * (
                                            CASE
                                                WHEN mpi.division_belt = 'BLACK' THEN
                                                    CASE
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 1 THEN 54.13
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 2 THEN 64.47
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 3 THEN 132.21
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 4 THEN 168.89
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 5 THEN 176.04
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 6 THEN 224.28
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 7 THEN 372.91
                                                        ELSE 435.37
                                                    END
                                                ELSE
                                                    CASE
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 1 THEN 23.33
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 2 THEN 60.99
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 3 THEN 73.56
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 4 THEN 119.93
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 5 THEN 181.59
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 6 THEN 224.28
                                                        WHEN ABS(mpi.team2_weight_index - mpi.team1_weight_index) = 7 THEN 372.91
                                                        ELSE 435.37
                                                    END
                                            END
                                        )
                                    ELSE 0
                                END
                            ELSE 0
                        END
                    ) AS team2_adjusted_rating
                FROM match_pairs_with_indices mpi
            ),
            team_results AS (
                SELECT
                    mp.team1_id AS team_id,
                    t1.name AS team_name,
                    CASE WHEN mp.team1_winner THEN 1 ELSE 0 END AS won,
                    mp.team2_adjusted_rating AS opponent_rating
                FROM match_pairs_adjusted mp
                JOIN teams t1 ON t1.id = mp.team1_id

                UNION ALL

                SELECT
                    mp.team2_id AS team_id,
                    t2.name AS team_name,
                    CASE WHEN mp.team2_winner THEN 1 ELSE 0 END AS won,
                    mp.team1_adjusted_rating AS opponent_rating
                FROM match_pairs_adjusted mp
                JOIN teams t2 ON t2.id = mp.team2_id
            ),
            team_aggregates AS (
                SELECT
                    team_id,
                    team_name,
                    SUM(won) AS wins,
                    ROUND(100.0 * SUM(won) / COUNT(*), 1) AS win_ratio,
                    AVG(CASE WHEN won = 1 THEN opponent_rating END) AS avg_defeated_rating,
                    (1.0 * SUM(won) / COUNT(*))
                    * COALESCE(AVG(CASE WHEN won = 1 THEN opponent_rating END), 0) AS adjusted_ratio
                FROM team_results
                GROUP BY team_id, team_name
                HAVING SUM(won) >= :min_wins_required
            ),
            ranked_teams AS (
                SELECT
                    team_name,
                    wins,
                    win_ratio,
                    avg_defeated_rating,
                    adjusted_ratio,
                    ROW_NUMBER() OVER (
                        ORDER BY
                            adjusted_ratio DESC,
                            win_ratio DESC,
                            COALESCE(avg_defeated_rating, 0) DESC,
                            team_name ASC
                    ) AS place
                FROM team_aggregates
            )
            SELECT
                place,
                team_name,
                wins,
                win_ratio,
                avg_defeated_rating,
                adjusted_ratio
            FROM ranked_teams
            WHERE place <= 10
            ORDER BY place
            """
        ),
        {
            "event_name": normalize(event_name),
            "rated": True,
            "min_wins_required": min_wins_required,
        },
    )

    teams = []
    for row in results:
        team = row._mapping
        teams.append(
            {
                "place": int(team["place"]),
                "team_name": team["team_name"],
                "wins": int(team["wins"]),
                "win_ratio": float(team["win_ratio"]),
                "avg_defeated_rating": (
                    float(team["avg_defeated_rating"])
                    if team["avg_defeated_rating"] is not None
                    else None
                ),
                "adjusted_ratio": float(team["adjusted_ratio"]),
            }
        )

    return jsonify({"teams": teams, "min_wins_required": int(min_wins_required)})
