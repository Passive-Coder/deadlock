CREATE TABLE IF NOT EXISTS snapshots (id VARCHAR(64), run_id VARCHAR(64), captured DOUBLE, complete DECIMAL(1,0));
CREATE TABLE IF NOT EXISTS workers (snapshot_id VARCHAR(64), run_id VARCHAR(64), id VARCHAR(64), attempt VARCHAR(64), "state" VARCHAR(32), progress DECIMAL(18,0), stage_version DECIMAL(18,0), checkpoint_id VARCHAR(64), checkpoint_version DECIMAL(18,0), checkpoint_work DECIMAL(18,0));
CREATE TABLE IF NOT EXISTS resources (snapshot_id VARCHAR(64), run_id VARCHAR(64), id VARCHAR(64), owner VARCHAR(64), version DECIMAL(18,0), capacity DECIMAL(4,0), exclusive DECIMAL(1,0));
CREATE TABLE IF NOT EXISTS waits (snapshot_id VARCHAR(64), run_id VARCHAR(64), worker_id VARCHAR(64), resource_id VARCHAR(64), version DECIMAL(18,0), blocking DECIMAL(1,0));
CREATE TABLE IF NOT EXISTS capabilities (snapshot_id VARCHAR(64), run_id VARCHAR(64), worker_id VARCHAR(64), operation VARCHAR(32), eligible DECIMAL(1,0), checkpoint_id VARCHAR(64), lost_work DECIMAL(18,0), version DECIMAL(18,0));
CREATE TABLE IF NOT EXISTS evidence (id VARCHAR(64), run_id VARCHAR(64), kind VARCHAR(32), created DOUBLE, payload VARCHAR(2000000));
