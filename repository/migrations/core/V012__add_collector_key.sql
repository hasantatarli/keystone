/*
===============================================================================
Migration No : 012
Version      : V012
Title        : Add Stable Collector Key

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds a stable system identifier to collector definitions.

collector_key is intended for internal application logic and remains stable
even if the collector display name, description, or script path changes.

Existing PostgreSQL collectors are backfilled with their initial stable keys.
===============================================================================
*/

ALTER TABLE keystone.collector_definition
ADD COLUMN collector_key VARCHAR(128) NULL;


UPDATE keystone.collector_definition
SET collector_key = 'PG_INSTANCE_INVENTORY'
WHERE component = 'PostgreSQL.Telemetry'
  AND name = 'Instance Inventory';


UPDATE keystone.collector_definition
SET collector_key = 'PG_CONFIGURATION_SNAPSHOT'
WHERE component = 'PostgreSQL.Telemetry'
  AND name = 'Configuration Snapshot';


ALTER TABLE keystone.collector_definition
ALTER COLUMN collector_key SET NOT NULL;


ALTER TABLE keystone.collector_definition
ADD CONSTRAINT uq_collector_definition_collector_key
UNIQUE (collector_key);