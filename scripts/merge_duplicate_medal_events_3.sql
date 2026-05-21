-- Third pass: merge the "Venice Jesolo ... 2024" duplicates that the medal
-- import created alongside the canonical "Venice ... 2024 (Results)" events.
-- Same shape as merge_duplicate_medal_events.sql — see that file's header
-- for the strategy.

BEGIN;

CREATE TEMP TABLE event_merges (
    duplicate_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO event_merges (duplicate_name, canonical_name) VALUES
    ('Venice Jesolo International Open IBJJF Jiu-Jitsu Championship 2024',
     'Venice International Open IBJJF Jiu-Jitsu Championship 2024 (Results)'),
    ('Venice Jesolo International Open IBJJF Jiu-Jitsu No-Gi Championship 2024',
     'Venice International Open IBJJF Jiu-Jitsu No-Gi Championship 2024 (Results)');

CREATE TEMP TABLE event_merge_ids ON COMMIT DROP AS
SELECT
    dup.id   AS duplicate_id,
    dup.name AS duplicate_name,
    can.id   AS canonical_id,
    can.name AS canonical_name
FROM event_merges em
JOIN events dup ON dup.name = em.duplicate_name
JOIN events can ON can.name = em.canonical_name;

DO $$
DECLARE
    expected INT;
    actual   INT;
BEGIN
    SELECT COUNT(*) INTO expected FROM event_merges;
    SELECT COUNT(*) INTO actual   FROM event_merge_ids;
    IF expected <> actual THEN
        RAISE EXCEPTION
            'event_merges: % pairs declared but only % resolved to events',
            expected, actual;
    END IF;
END $$;

DO $$
DECLARE
    bad_count INT;
BEGIN
    SELECT COUNT(*)
      INTO bad_count
      FROM event_merge_ids emi
      JOIN events e ON e.id = emi.duplicate_id
     WHERE e.medals_only IS NOT TRUE;
    IF bad_count > 0 THEN
        RAISE EXCEPTION
            '% duplicate events are not medals_only — aborting',
            bad_count;
    END IF;
END $$;

UPDATE medals m
   SET event_id = emi.canonical_id
  FROM event_merge_ids emi
 WHERE m.event_id = emi.duplicate_id
   AND NOT EXISTS (
        SELECT 1
          FROM medals m2
         WHERE m2.event_id     = emi.canonical_id
           AND m2.division_id  = m.division_id
           AND m2.athlete_id   = m.athlete_id
   );

DELETE FROM medals m
 USING event_merge_ids emi
 WHERE m.event_id = emi.duplicate_id;

DELETE FROM events e
 USING event_merge_ids emi
 WHERE e.id = emi.duplicate_id;

COMMIT;
