/*
===============================================================================
Migration No : 035
Version      : V035
Title        : Replication Lag Finding Text

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
PG-REP-003 findings state the measured lag and, for a deliberately delayed
replica, the part beyond the intended apply delay.
===============================================================================
*/


/*
Design notes (2026-10-21, Hasan)
--------------------------------
With an intended delay of 5 minutes and a measured lag of 6 minutes, a finding
saying "1 minute behind" understates what was measured. The observed value is
the measured lag; the threshold applies to the part beyond the delay; both are
shown.
===============================================================================
*/

UPDATE keystone.rule_definition
SET finding_template = 'Replica {replica} is {lag_seconds} seconds behind the primary in replaying changes{delay_note}.'
WHERE rule_key = 'PG-REP-003';
