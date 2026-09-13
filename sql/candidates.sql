SELECT c.worker_id, c.operation, c.checkpoint_id, c.lost_work, c.version,
       w.checkpoint_work, w.attempt
FROM capabilities c
JOIN workers w ON w.snapshot_id=c.snapshot_id AND w.run_id=c.run_id AND w.id=c.worker_id
JOIN snapshots s ON s.id=c.snapshot_id AND s.run_id=c.run_id
WHERE c.snapshot_id={sid} AND c.run_id={rid} AND s.complete=1
  AND c.eligible=1 AND w."state"='WAITING'
ORDER BY c.lost_work, c.worker_id, c.operation
