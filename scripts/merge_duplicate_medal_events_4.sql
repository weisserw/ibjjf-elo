-- Fourth pass: clean up the medal corruption introduced by silently-deduped
-- mislabeled IBJJF index links. See KNOWN_BAD_LINKS in scripts/get_medals.py
-- and the conversation thread for context.
--
-- Two groups in one transaction:
--   Group A — six phantom Kids events that hold main-event data (gi/gi, no
--             division swap needed). Migrate medals to the main event, then
--             delete the phantom. Same shape as merge_duplicate_medal_events_3.
--   Group C — division-swap pass: every gi=TRUE medal on Curitiba Summer
--             International Open IBJJF Jiu-Jitsu No-Gi Championship 2026
--             gets its division_id moved to the gi=FALSE sibling division.
--             If a correct gi=FALSE medal already exists for the same
--             (athlete, event), the bogus gi=TRUE row is deleted instead.
--
-- NOTE: An earlier draft had a Group B that migrated medals from a phantom
-- 'Kids International IBJJF Jiu-Jitsu Championship - Florianópolis 2026'
-- event into Curitiba No-Gi 2026. Investigation showed those 181 medals are
-- actually legitimate Florianópolis Kids 2026 data (all kids belts / teen
-- ages, zero overlap with the bogus 348 on Curitiba No-Gi) captured by an
-- earlier scrape of a now-broken IBJJF link. They stay on the Florianópolis
-- event; only the bogus Curitiba medals get cleaned up.
--
-- Final assertion confirms no medal in the DB still has its event-name
-- no-gi-ness disagreeing with its division.gi.

BEGIN;

-- ---------------------------------------------------------------------------
-- Group A: phantom Kids event → main event medal migration.
-- ---------------------------------------------------------------------------

CREATE TEMP TABLE event_merges (
    duplicate_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL
) ON COMMIT DROP;

INSERT INTO event_merges (duplicate_name, canonical_name) VALUES
    ('American National Kids IBJJF Jiu-Jitsu Championship 2015',
     'American National IBJJF Jiu-Jitsu Championship 2015'),
    ('American National Kids IBJJF Jiu-Jitsu Championship 2016',
     'American National IBJJF Jiu-Jitsu Championship 2016'),
    ('American National Kids IBJJF Jiu-Jitsu Championship 2017',
     'American National IBJJF Jiu-Jitsu Championship 2017'),
    ('American National Kids IBJJF Jiu-Jitsu Championship 2018',
     'American National IBJJF Jiu-Jitsu Championship 2018'),
    ('British National Kids IBJJF Jiu-Jitsu Championship 2016',
     'British National IBJJF Jiu-Jitsu Championship 2016'),
    ('Chicago Summer Kids International Open IBJJF Jiu-Jitsu Championship 2016',
     'Chicago Summer International Open IBJJF Jiu-Jitsu Championship 2016');

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

DO $$
DECLARE
    rec        RECORD;
    pre_count  INT;
    migrated   INT;
    deleted    INT;
BEGIN
    FOR rec IN SELECT * FROM event_merge_ids ORDER BY duplicate_name LOOP
        SELECT COUNT(*) INTO pre_count
          FROM medals
         WHERE event_id = rec.duplicate_id;

        UPDATE medals m
           SET event_id = rec.canonical_id
         WHERE m.event_id = rec.duplicate_id
           AND NOT EXISTS (
                SELECT 1
                  FROM medals m2
                 WHERE m2.event_id    = rec.canonical_id
                   AND m2.division_id = m.division_id
                   AND m2.athlete_id  = m.athlete_id
           );
        GET DIAGNOSTICS migrated = ROW_COUNT;

        DELETE FROM medals
         WHERE event_id = rec.duplicate_id;
        GET DIAGNOSTICS deleted = ROW_COUNT;

        RAISE NOTICE
            '[merge] % -> %: % on phantom, % migrated, % deleted as duplicates',
            rec.duplicate_name, rec.canonical_name, pre_count, migrated, deleted;
    END LOOP;
END $$;

DELETE FROM events e
 USING event_merge_ids emi
 WHERE e.id = emi.duplicate_id;


-- ---------------------------------------------------------------------------
-- Group C: gi-flag swap on Curitiba No-Gi 2026.
-- ---------------------------------------------------------------------------
--
-- The 348 gi=TRUE medals on this no-gi event came from result_medals rows
-- mislabeled "Florianópolis Kids 2026" that find_event short-circuited onto
-- the Curitiba No-Gi event via ibjjf_id=3086. Data is real Curitiba No-Gi
-- data — just under gi=TRUE divisions instead of gi=FALSE. Swap each to the
-- gi=FALSE sibling division; delete where a correct gi=FALSE medal already
-- exists for the same (athlete, event).

-- Sanity-check: every (belt, age, gender, weight) combo we're about to
-- swap actually has a gi=FALSE sibling division to swap to. If any combo
-- is missing one, abort rather than silently leave bogus rows behind.
DO $$
DECLARE
    missing INT;
BEGIN
    SELECT COUNT(*)
      INTO missing
      FROM (
        SELECT DISTINCT d.belt, d.age, d.gender, d.weight
          FROM medals m
          JOIN divisions d ON d.id = m.division_id
          JOIN events e    ON e.id = m.event_id
         WHERE e.name = 'Curitiba Summer International Open IBJJF Jiu-Jitsu No-Gi Championship 2026'
           AND d.gi = TRUE
      ) bad
     WHERE NOT EXISTS (
        SELECT 1
          FROM divisions ds
         WHERE ds.belt   = bad.belt
           AND ds.age    = bad.age
           AND ds.gender = bad.gender
           AND ds.weight = bad.weight
           AND ds.gi     = FALSE
     );
    IF missing > 0 THEN
        RAISE EXCEPTION
            '% (belt, age, gender, weight) combos on bogus gi=TRUE medals '
            'lack a gi=FALSE sibling division — cannot swap',
            missing;
    END IF;
END $$;

DO $$
DECLARE
    pre_count INT;
    swapped   INT;
    deleted   INT;
BEGIN
    SELECT COUNT(*) INTO pre_count
      FROM medals m
      JOIN divisions d ON d.id = m.division_id
      JOIN events    e ON e.id = m.event_id
     WHERE e.name = 'Curitiba Summer International Open IBJJF Jiu-Jitsu No-Gi Championship 2026'
       AND d.gi   = TRUE;

    UPDATE medals m
       SET division_id = ds.id
      FROM divisions d, divisions ds, events e
     WHERE m.division_id = d.id
       AND m.event_id    = e.id
       AND e.name        = 'Curitiba Summer International Open IBJJF Jiu-Jitsu No-Gi Championship 2026'
       AND d.gi          = TRUE
       AND ds.belt       = d.belt
       AND ds.age        = d.age
       AND ds.gender     = d.gender
       AND ds.weight     = d.weight
       AND ds.gi         = FALSE
       AND NOT EXISTS (
            SELECT 1
              FROM medals m2
             WHERE m2.event_id    = m.event_id
               AND m2.athlete_id  = m.athlete_id
               AND m2.division_id = ds.id
       );
    GET DIAGNOSTICS swapped = ROW_COUNT;

    DELETE FROM medals m
     USING divisions d, events e
     WHERE m.division_id = d.id
       AND m.event_id    = e.id
       AND e.name        = 'Curitiba Summer International Open IBJJF Jiu-Jitsu No-Gi Championship 2026'
       AND d.gi          = TRUE;
    GET DIAGNOSTICS deleted = ROW_COUNT;

    RAISE NOTICE
        '[gi-swap] Curitiba No-Gi 2026: % bogus gi=TRUE medals, % swapped to gi=FALSE sibling, % deleted as duplicates',
        pre_count, swapped, deleted;
END $$;


-- ---------------------------------------------------------------------------
-- Final assertion: no medal anywhere has gi-flag corruption left.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    remaining INT;
BEGIN
    SELECT COUNT(*)
      INTO remaining
      FROM medals m
      JOIN events e    ON e.id = m.event_id
      JOIN divisions d ON d.id = m.division_id
     WHERE (e.name ILIKE '%no-gi%'
         OR e.name ILIKE '%no gi%'
         OR e.name ILIKE '%sem kimono%') = d.gi;
    IF remaining > 0 THEN
        RAISE EXCEPTION
            '% medals still have gi-mismatch between event name and '
            'division.gi after cleanup',
            remaining;
    END IF;
    RAISE NOTICE '[final] gi-mismatch sweep clean — 0 remaining';
END $$;

COMMIT;
