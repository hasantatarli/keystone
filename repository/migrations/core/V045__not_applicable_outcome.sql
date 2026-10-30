/*
===============================================================================
Migration No : 045
Version      : V045
Title        : NOT_APPLICABLE Assessment Outcome

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds NOT_APPLICABLE to assessment results (ADR-0014 addendum): the rule's
premise does not exist on the system, e.g. replication lag on a server without
replicas. Not a finding, not missing data, not counted as a check done.
===============================================================================
*/

ALTER TABLE keystone.assessment_result
    DROP CONSTRAINT ck_assessment_result_outcome;

ALTER TABLE keystone.assessment_result
    ADD CONSTRAINT ck_assessment_result_outcome
        CHECK (
            outcome IN (
                'HEALTHY',
                'ATTENTION_REQUIRED',
                'INSUFFICIENT_EVIDENCE',
                'NOT_APPLICABLE',
                'ERROR'
            )
        );
