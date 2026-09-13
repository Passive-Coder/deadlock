WITH edges AS (
    SELECT q.worker_id AS waiter, r.owner AS holder, r.id AS resource_id
    FROM waits q
    JOIN resources r ON r.snapshot_id=q.snapshot_id AND r.run_id=q.run_id AND r.id=q.resource_id
    JOIN snapshots s ON s.id=q.snapshot_id AND s.run_id=q.run_id
    JOIN workers w ON w.snapshot_id=q.snapshot_id AND w.run_id=q.run_id AND w.id=q.worker_id
    WHERE s.id={sid} AND s.run_id={rid} AND s.complete=1
      AND q.blocking=1 AND r.capacity=1 AND r.exclusive=1
      AND w."state"='WAITING' AND r.owner IS NOT NULL AND r.owner<>q.worker_id
)
SELECT a.waiter AS a, b.waiter AS b, '' AS c, a.resource_id AS ra, b.resource_id AS rb, '' AS rc
FROM edges a JOIN edges b ON a.holder=b.waiter AND b.holder=a.waiter
WHERE a.waiter<b.waiter
UNION ALL
SELECT a.waiter, b.waiter, c.waiter, a.resource_id, b.resource_id, c.resource_id
FROM edges a JOIN edges b ON a.holder=b.waiter
JOIN edges c ON b.holder=c.waiter AND c.holder=a.waiter
WHERE a.waiter<b.waiter AND a.waiter<c.waiter AND b.waiter<>c.waiter
