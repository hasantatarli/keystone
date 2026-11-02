/*
===============================================================================
Migration No    : 020
Version         : PG020
Title           : Checkpoint Statistics Snapshot

Author          : Hasan Tatarlı
Applies To      : PostgreSQL
Execution Scope : SYSTEM

Description
-----------
Creates the repository table for PG_CHECKPOINT_STATS: timed and requested
checkpoints since the statistics were reset (ADR-0017 step 3b).
===============================================================================
*/

CREATE TABLE postgresql.checkpoint_stats_snapshot
(
    snapshot_id            BIGSERIAL PRIMARY KEY,
    target_id              BIGINT      NOT NULL,
    captured_at            TIMESTAMPTZ NOT NULL,
    in_recovery            BOOLEAN     NOT NULL,
    checkpoints_timed      BIGINT      NOT NULL,
    checkpoints_requested  BIGINT      NOT NULL,
    stats_reset            TIMESTAMPTZ
);

COMMENT ON TABLE postgresql.checkpoint_stats_snapshot IS
'Checkpoints since stats_reset: timed (checkpoint_timeout) and requested (mostly WAL reaching max_wal_size).';

CREATE INDEX ix_checkpoint_stats_snapshot_target_captured
    ON postgresql.checkpoint_stats_snapshot
    (target_id, captured_at DESC);
