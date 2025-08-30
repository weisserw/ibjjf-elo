WITH highest_matches AS (
  SELECT id
  FROM matches
  WHERE event_id = '8a97bdd0-40de-4a74-a319-fc3c83cf743b'
    AND (division_id, match_number) IN (
      SELECT division_id, MAX(match_number)
      FROM matches
      WHERE event_id = '8a97bdd0-40de-4a74-a319-fc3c83cf743b'
      GROUP BY division_id
    )
)
SELECT
  a1.name,
  mp1.start_rating,
  a2.name,
  mp2.start_rating
FROM highest_matches hm
JOIN match_participants mp1 ON hm.id = mp1.match_id AND mp1.winner and mp1.start_match_count > 5
JOIN athletes a1 ON a1.id = mp1.athlete_id
JOIN match_participants mp2 ON hm.id = mp2.match_id AND NOT mp2.winner and mp2.start_match_count > 5
JOIN athletes a2 ON a2.id = mp2.athlete_id
ORDER BY mp1.start_rating - mp2.start_rating