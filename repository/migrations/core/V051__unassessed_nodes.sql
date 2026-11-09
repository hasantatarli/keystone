/*
===============================================================================
Migration No : 051
Version      : V051
Title        : Unassessed Nodes

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Records per rule result the nodes the rule could not judge (evidence not
collected or stale on that node, no disk or memory data). Findings on other
nodes stay; a result without findings and with unassessed nodes is
INSUFFICIENT_EVIDENCE, never HEALTHY (review 2026-11-09).
===============================================================================
*/

ALTER TABLE keystone.assessment_result
    ADD COLUMN unassessed JSONB;

COMMENT ON COLUMN keystone.assessment_result.unassessed IS
'Nodes the rule could not judge: [{"target_id", "node", "source", "reason_code"}]. NULL when every node was judged.';
