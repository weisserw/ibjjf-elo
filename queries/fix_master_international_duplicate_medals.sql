BEGIN;

CREATE TEMP TABLE duplicate_event_merges (
    source_event_id uuid PRIMARY KEY,
    target_event_id uuid NOT NULL,
    source_event_name text NOT NULL,
    target_event_name text NOT NULL
) ON COMMIT DROP;

INSERT INTO duplicate_event_merges (
    source_event_id,
    target_event_id,
    source_event_name,
    target_event_name
)
VALUES
    (
        '7713b1c0-9b78-4eb9-aa39-ecf03cf13ca3',
        '4255926e-5698-4547-b566-d5f5a401ec43',
        'Master International Jiu-Jitsu IBJJF Championship – South America 2022',
        'Master International Jiu-Jitsu Championship - South America 2022 (Results)'
    ),
    (
        '48101aa0-5b4f-4dcc-b901-2b43feb3bcd9',
        'ed969e8d-a4e7-44fb-a3d0-bda7bfcdd076',
        'Master International Jiu-Jitsu IBJJF Championship – South America 2023',
        'Master International Jiu-Jitsu Championship - South America 2023 (Results)'
    ),
    (
        '83291d4a-340a-4c50-bbf3-30beba84b843',
        'd9223093-0c0a-416e-97fe-78ad0f447362',
        'Master International Jiu-Jitsu IBJJF Championship – South America 2024',
        'Master International Jiu-Jitsu Championship - South America 2024 (Results)'
    ),
    (
        'fdcf58b8-ee2e-4715-8e6b-a76d187999ce',
        'd0db74fe-2e53-4a33-8646-5ee94cde08ca',
        'Master International Jiu-Jitsu IBJJF Championship – Europe 2022',
        'Master International Jiu-Jitsu Championship - Europe 2022 (Results)'
    ),
    (
        '60d83309-5b72-4303-8fbc-97e42ac62083',
        'ac4a96db-7f6c-45fb-ab03-df4cf6d0c0fb',
        'Master International Jiu-Jitsu IBJJF Championship – Europe 2023',
        'Master International Jiu-Jitsu Championship - Europe 2023 (Results)'
    ),
    (
        '1925a50d-9a4a-4a54-92a8-bf825c3c04b3',
        'df388065-aca4-4a96-94ce-aeb205cd3cc5',
        'Master International Jiu-Jitsu IBJJF Championship – Europe 2024',
        'Master International Jiu-Jitsu Championship - Europe 2024 (Results)'
    ),
    (
        '82e4482c-a281-4673-86a9-28cf5ebbe7cc',
        'd2ce03cf-20d5-40c0-8e96-92987101a757',
        'Master International Jiu-Jitsu IBJJF Championship – North America 2022',
        'Master International Jiu-Jitsu IBJJF Championship – North America 2022 (Archive)'
    ),
    (
        'ed7f949c-a6e1-425c-a72b-6666b0839c2c',
        '4bd3c28d-0a8b-41ee-8238-ca198a55f9ad',
        'Master International Jiu-Jitsu IBJJF Championship – North America 2023',
        'Master International Jiu-Jitsu Championship - North America 2023 (Flo)'
    ),
    (
        '6f20f454-6a73-4478-9c28-53177a018245',
        '05193c65-c9b2-4f8c-8c44-a4dbfae6756f',
        'Master International Jiu-Jitsu IBJJF Championship – North America 2024',
        'Master International Jiu-Jitsu Championship - North America 2024 (Flo)'
    );

DO $$
DECLARE
    merge_row record;
    source_event_count integer;
    target_event_count integer;
    source_match_count integer;
    source_medal_count integer;
BEGIN
    FOR merge_row IN
        SELECT * FROM duplicate_event_merges ORDER BY source_event_name
    LOOP
        SELECT COUNT(*)
        INTO source_event_count
        FROM events
        WHERE id = merge_row.source_event_id;

        IF source_event_count = 0 THEN
            SELECT COUNT(*)
            INTO source_medal_count
            FROM medals
            WHERE event_id = merge_row.source_event_id;

            IF source_medal_count <> 0 THEN
                RAISE EXCEPTION 'Source event % (%) is missing but still has % medals',
                    merge_row.source_event_id, merge_row.source_event_name, source_medal_count;
            END IF;

            SELECT COUNT(*)
            INTO target_event_count
            FROM events
            WHERE id = merge_row.target_event_id
              AND name = merge_row.target_event_name;

            IF target_event_count <> 1 THEN
                RAISE EXCEPTION 'Expected exactly one target event % (%), found %',
                    merge_row.target_event_id, merge_row.target_event_name, target_event_count;
            END IF;

            RAISE NOTICE 'Source event % (%) already absent; skipping validation',
                merge_row.source_event_id, merge_row.source_event_name;
            CONTINUE;
        END IF;

        SELECT COUNT(*)
        INTO source_event_count
        FROM events
        WHERE id = merge_row.source_event_id
          AND name = merge_row.source_event_name
          AND medals_only IS TRUE;

        IF source_event_count <> 1 THEN
            RAISE EXCEPTION 'Source event % must exist with expected name and medals_only=true: %',
                merge_row.source_event_id, merge_row.source_event_name;
        END IF;

        SELECT COUNT(*)
        INTO target_event_count
        FROM events
        WHERE id = merge_row.target_event_id
          AND name = merge_row.target_event_name;

        IF target_event_count <> 1 THEN
            RAISE EXCEPTION 'Expected exactly one target event % (%), found %',
                merge_row.target_event_id, merge_row.target_event_name, target_event_count;
        END IF;

        SELECT COUNT(*)
        INTO source_match_count
        FROM matches
        WHERE event_id = merge_row.source_event_id;

        IF source_match_count <> 0 THEN
            RAISE EXCEPTION 'Source event % (%) has % matches; refusing to merge medals',
                merge_row.source_event_id, merge_row.source_event_name, source_match_count;
        END IF;
    END LOOP;
END $$;

SELECT
    merge.source_event_name,
    merge.target_event_name,
    COUNT(DISTINCT source_medal.id) AS source_medals_before,
    COUNT(DISTINCT target_medal.id) AS target_medals_before,
    COUNT(DISTINCT duplicate_target_medal.id) AS duplicate_source_medals_to_delete
FROM duplicate_event_merges merge
LEFT JOIN medals source_medal
    ON source_medal.event_id = merge.source_event_id
LEFT JOIN medals target_medal
    ON target_medal.event_id = merge.target_event_id
LEFT JOIN medals duplicate_target_medal
    ON duplicate_target_medal.event_id = merge.target_event_id
   AND duplicate_target_medal.division_id = source_medal.division_id
   AND duplicate_target_medal.athlete_id = source_medal.athlete_id
GROUP BY merge.source_event_name, merge.target_event_name
ORDER BY merge.source_event_name;

WITH deleted_duplicate_medals AS (
    DELETE FROM medals source_medal
    USING medals target_medal, duplicate_event_merges merge
    WHERE source_medal.event_id = merge.source_event_id
      AND target_medal.event_id = merge.target_event_id
      AND target_medal.division_id = source_medal.division_id
      AND target_medal.athlete_id = source_medal.athlete_id
    RETURNING source_medal.event_id
)
SELECT
    merge.source_event_name,
    COUNT(deleted.event_id) AS duplicate_medals_deleted
FROM duplicate_event_merges merge
LEFT JOIN deleted_duplicate_medals deleted
    ON deleted.event_id = merge.source_event_id
GROUP BY merge.source_event_name
ORDER BY merge.source_event_name;

WITH moved_source_medals AS (
    UPDATE medals medal
    SET event_id = merge.target_event_id
    FROM duplicate_event_merges merge
    WHERE medal.event_id = merge.source_event_id
    RETURNING medal.event_id
)
SELECT
    merge.source_event_name,
    merge.target_event_name,
    COUNT(moved.event_id) AS medals_moved_to_target_event
FROM duplicate_event_merges merge
LEFT JOIN moved_source_medals moved
    ON moved.event_id = merge.target_event_id
GROUP BY merge.source_event_name, merge.target_event_name
ORDER BY merge.source_event_name;

WITH deleted_duplicate_events AS (
    DELETE FROM events event
    USING duplicate_event_merges merge
    WHERE event.id = merge.source_event_id
    RETURNING event.id
)
SELECT
    merge.source_event_name,
    COUNT(deleted.id) AS source_events_deleted
FROM duplicate_event_merges merge
LEFT JOIN deleted_duplicate_events deleted
    ON deleted.id = merge.source_event_id
GROUP BY merge.source_event_name
ORDER BY merge.source_event_name;

DO $$
DECLARE
    remaining_source_medals integer;
    remaining_source_events integer;
BEGIN
    SELECT COUNT(*)
    INTO remaining_source_medals
    FROM medals medal
    JOIN duplicate_event_merges merge
        ON merge.source_event_id = medal.event_id;

    IF remaining_source_medals <> 0 THEN
        RAISE EXCEPTION 'Source events still have % medals after merge',
            remaining_source_medals;
    END IF;

    SELECT COUNT(*)
    INTO remaining_source_events
    FROM events event
    JOIN duplicate_event_merges merge
        ON merge.source_event_id = event.id;

    IF remaining_source_events <> 0 THEN
        RAISE EXCEPTION 'Found % source events still present after delete',
            remaining_source_events;
    END IF;
END $$;

COMMIT;
