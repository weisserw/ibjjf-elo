BEGIN;

SELECT id, archive_id, status, queue_requested_at
FROM livestream_frame_text_scans
WHERE archive_id = 'b9f59ef3-c0f3-4efe-8e42-34293ee7c562'
FOR UPDATE;

UPDATE livestream_frame_text_scans AS scan
SET queue_requested_at = TIMESTAMP '1970-01-01 00:00:00',
    updated_at = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
WHERE scan.archive_id = 'b9f59ef3-c0f3-4efe-8e42-34293ee7c562'
  AND EXISTS (
      SELECT 1
      FROM livestream_frame_text_scan_segments AS segment
      WHERE segment.scan_id = scan.id
        AND segment.status = 'queued'
  )
RETURNING id, archive_id, status, queue_requested_at;

COMMIT;