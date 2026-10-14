/*
===============================================================================
Migration No : 024
Version      : V024
Title        : Event Log

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds keystone.event_log for significant technical events (WARNING and above,
component start and stop) so they can be queried and later shown in the user
interface. Implements the repository layer of ADR-0014 logging.
===============================================================================
*/


/*
Design notes (ADR-0014)
-----------------------
All technical log records go to a rotating log file. Only significant events
are also written here, through a separate autocommit connection, so an event
is not rolled back together with the failed work it describes. If this table
cannot be written, the record still reaches the log file.

Business events (collector runs, assessment runs and results, findings) stay
in their own tables; this table is for technical events.

A retention policy is deferred until continuous operation produces volume.
===============================================================================
*/

CREATE TABLE keystone.event_log
(
    event_id     BIGINT GENERATED ALWAYS AS IDENTITY,

    logged_at    TIMESTAMPTZ   NOT NULL,
    level        VARCHAR(10)   NOT NULL,

    /*
    Keystone component that produced the event, for example
    assessment_engine, worker or installer.
    */
    component    VARCHAR(50)   NOT NULL,
    logger_name  VARCHAR(200)  NOT NULL,
    message      TEXT          NOT NULL,

    /*
    Exception type, message and traceback when the event was logged with
    exception information.
    */
    exception    TEXT,

    /*
    Structured identifiers related to the event, for example
    {"assessment_run_id": 42, "rule_key": "PG-TRAN-001"}.
    */
    context      JSONB,

    hostname     VARCHAR(255),
    process_id   INTEGER,

    CONSTRAINT pk_event_log
        PRIMARY KEY (event_id),

    CONSTRAINT ck_event_log_level
        CHECK (
            level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        )
);

CREATE INDEX ix_event_log_logged_at
    ON keystone.event_log (logged_at DESC);

CREATE INDEX ix_event_log_component_level
    ON keystone.event_log (component, level, logged_at DESC);
