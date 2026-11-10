/*
===============================================================================
Migration No : 054
Version      : V054
Title        : Offline Health Check

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
A health check can be built from offline evidence (MVP Plan Phase 1): files
the customer produced with the read-only scripts, imported later. The check
records where its evidence came from and when it was captured and imported.
===============================================================================
*/

ALTER TABLE keystone.health_check
    ADD COLUMN source      VARCHAR(10) NOT NULL DEFAULT 'LIVE',
    ADD COLUMN imported_at TIMESTAMPTZ,
    ADD COLUMN bundle_info JSONB,
    ADD CONSTRAINT ck_health_check_source CHECK (source IN ('LIVE', 'OFFLINE'));

COMMENT ON COLUMN keystone.health_check.source IS
'LIVE: collected by Keystone over its connections; OFFLINE: imported from evidence files (started_at / finished_at are the capture times).';

COMMENT ON COLUMN keystone.health_check.bundle_info IS
'Offline files: [{"file", "sha256", "kind", "node", "database", "captured_at", "system_identifier", "address"}] and warnings.';
