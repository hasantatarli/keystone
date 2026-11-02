/*
===============================================================================
Migration No : 049
Version      : V049
Title        : Configuration Recommendation Restart and Assumptions

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
ADR-0017 step 4: what the report shows next to a recommendation is stored with
it, so an old report stays as the customer saw it: whether the setting needs a
restart (pg_settings.context = postmaster) and which assumed profile values the
recommendation rests on.
===============================================================================
*/

ALTER TABLE keystone.config_recommendation
    ADD COLUMN restart_required BOOLEAN,
    ADD COLUMN assumptions      JSONB;

COMMENT ON COLUMN keystone.config_recommendation.restart_required IS
'The setting takes effect only after a restart (context postmaster on the primary).';
COMMENT ON COLUMN keystone.config_recommendation.assumptions IS
'Profile fields the recommendation depends on that were not given: ["storage_type", ...].';
