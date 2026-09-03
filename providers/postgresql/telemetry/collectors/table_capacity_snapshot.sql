/*
===============================================================================
Key        : PG_TABLE_CAPACITY
Name       : Table & Index Capacity
Component  : PostgreSQL.Telemetry
Applies To : PostgreSQL
Execution Scope : DATABASE

Description
-----------
Collects logical table and materialized view capacity information including
data, index and TOAST sizes, partition count, tablespace summary and estimated
row count.
===============================================================================
*/



WITH RECURSIVE
snapshot AS
(
    SELECT statement_timestamp() AS captured_at
),

base_objects AS
(
    SELECT
        c.oid AS object_oid,
        n.nspname AS schema_name,
        c.relname AS object_name,
        c.relkind,
        c.relpersistence,
        c.relispartition,
        c.reltuples,
        c.reltablespace,
        c.reltoastrelid
    FROM pg_class c
    JOIN pg_namespace n
        ON n.oid = c.relnamespace
    WHERE c.relkind IN ('r', 'p', 'm')
      AND n.nspname NOT IN
      (
          'pg_catalog',
          'information_schema'
      )
      AND n.nspname NOT LIKE 'pg_toast%'
),

partition_tree AS
(
    SELECT
        parent.oid AS root_oid,
        child.oid AS child_oid,
        child.relkind
    FROM pg_class parent
    JOIN pg_inherits i
        ON i.inhparent = parent.oid
    JOIN pg_class child
        ON child.oid = i.inhrelid
    WHERE parent.relkind = 'p'

    UNION ALL

    SELECT
        pt.root_oid,
        child.oid AS child_oid,
        child.relkind
    FROM partition_tree pt
    JOIN pg_inherits i
        ON i.inhparent = pt.child_oid
    JOIN pg_class child
        ON child.oid = i.inhrelid
),

leaf_partitions AS
(
    SELECT
        pt.root_oid,
        pt.child_oid
    FROM partition_tree pt
    WHERE NOT EXISTS
    (
        SELECT 1
        FROM pg_inherits i
        WHERE i.inhparent = pt.child_oid
    )
),

logical_objects AS
(
    SELECT
        bo.object_oid,
        bo.schema_name,
        bo.object_name,
        bo.relkind,
        bo.relpersistence,
        bo.reltuples,
        bo.reltablespace,
        bo.reltoastrelid
    FROM base_objects bo
    WHERE bo.relispartition = false
),

physical_relations AS
(
    SELECT
        lo.object_oid AS logical_object_oid,
        lo.object_oid AS physical_oid
    FROM logical_objects lo
    WHERE lo.relkind IN ('r', 'm')

    UNION ALL

    SELECT
        lo.object_oid AS logical_object_oid,
        lp.child_oid AS physical_oid
    FROM logical_objects lo
    JOIN leaf_partitions lp
        ON lp.root_oid = lo.object_oid
    WHERE lo.relkind = 'p'
),

physical_sizes AS
(
    SELECT
        pr.logical_object_oid,

        SUM(
            pg_table_size(pr.physical_oid)
            -
            CASE
                WHEN pc.reltoastrelid <> 0
                    THEN pg_total_relation_size(pc.reltoastrelid)
                ELSE 0
            END
        )::bigint AS data_size_bytes,

        SUM(
            pg_indexes_size(pr.physical_oid)
        )::bigint AS indexes_size_bytes,

        SUM(
            CASE
                WHEN pc.reltoastrelid <> 0
                    THEN pg_total_relation_size(pc.reltoastrelid)
                ELSE 0
            END
        )::bigint AS toast_size_bytes,

        SUM(
            pg_total_relation_size(pr.physical_oid)
        )::bigint AS total_size_bytes,

        SUM(
            CASE
                WHEN pc.reltuples >= 0
                    THEN pc.reltuples
                ELSE NULL
            END
        )::bigint AS estimated_rows

    FROM physical_relations pr
    JOIN pg_class pc
        ON pc.oid = pr.physical_oid
    GROUP BY pr.logical_object_oid
),

partition_counts AS
(
    SELECT
        root_oid AS logical_object_oid,
        COUNT(*)::integer AS partition_count
    FROM leaf_partitions
    GROUP BY root_oid
),

logical_index_counts AS
(
    SELECT
        i.indrelid AS logical_object_oid,
        COUNT(*)::integer AS index_count
    FROM pg_index i
    JOIN pg_class c
        ON c.oid = i.indrelid
    WHERE c.relispartition = false
    GROUP BY i.indrelid
),

tablespace_summary AS
(
    SELECT
        pr.logical_object_oid,
        string_agg(
            DISTINCT ts.spcname,
            ','
            ORDER BY ts.spcname
        ) AS tablespace_names
    FROM physical_relations pr
    JOIN pg_class pc
        ON pc.oid = pr.physical_oid
    JOIN pg_database db
        ON db.datname = current_database()
    JOIN pg_tablespace ts
        ON ts.oid =
            CASE
                WHEN pc.reltablespace = 0
                    THEN db.dattablespace
                ELSE pc.reltablespace
            END
    GROUP BY pr.logical_object_oid
)

SELECT
    (
	    SELECT oid
	    FROM pg_database
	    WHERE datname = current_database()
	) AS database_oid,
    current_database() AS database_name,

    lo.schema_name,
    lo.object_oid,
    lo.object_name,

    CASE
        WHEN lo.relkind = 'm'
            THEN 'MATERIALIZED_VIEW'
        ELSE 'TABLE'
    END AS object_type,

    (lo.relkind = 'p') AS is_partitioned,

    COALESCE(pc.partition_count, 0) AS partition_count,

    ts.tablespace_names,

    COALESCE(ps.data_size_bytes, 0) AS data_size_bytes,
	COALESCE(ps.indexes_size_bytes, 0) AS indexes_size_bytes,
	COALESCE(ps.toast_size_bytes, 0) AS toast_size_bytes,
	COALESCE(ps.total_size_bytes, 0) AS total_size_bytes,

	CASE
	    WHEN lo.relkind = 'p'
	        THEN ps.estimated_rows
	    WHEN lo.reltuples >= 0
	        THEN lo.reltuples::bigint
	    ELSE NULL
	END AS estimated_rows,

    COALESCE(ic.index_count, 0) AS index_count,

    snap.captured_at

FROM logical_objects lo
CROSS JOIN snapshot snap
LEFT JOIN physical_sizes ps
    ON ps.logical_object_oid = lo.object_oid
LEFT JOIN partition_counts pc
    ON pc.logical_object_oid = lo.object_oid
LEFT JOIN logical_index_counts ic
    ON ic.logical_object_oid = lo.object_oid
LEFT JOIN tablespace_summary ts
    ON ts.logical_object_oid = lo.object_oid

ORDER BY
    lo.schema_name,
    ps.total_size_bytes DESC NULLS LAST,
    lo.object_name;