/*
===============================================================================
Migration No : 055
Version      : V055
Title        : Target Identity

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Every name a server was reached by (as typed, as resolved, as PostgreSQL
reports itself), with the port. Offline evidence is matched to a node if any
of them was seen before, so the same server is one node whether the customer
typed its address or its host name (Hasan, 2026-11-10).
===============================================================================
*/

CREATE TABLE keystone.target_identity
(
    target_id   BIGINT       NOT NULL,
    identity    VARCHAR(300) NOT NULL,     -- 'host:port' or a bare name, lower case
    source      VARCHAR(20)  NOT NULL,     -- OFFLINE
    first_seen  TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),
    last_seen   TIMESTAMPTZ  NOT NULL DEFAULT clock_timestamp(),

    CONSTRAINT pk_target_identity PRIMARY KEY (target_id, identity),
    CONSTRAINT fk_target_identity_target FOREIGN KEY (target_id) REFERENCES keystone.target (target_id)
);

CREATE INDEX ix_target_identity_identity ON keystone.target_identity (identity);

COMMENT ON TABLE keystone.target_identity IS
'Names a node was reached by in offline evidence (typed, resolved, reported by PostgreSQL), with the port.';
