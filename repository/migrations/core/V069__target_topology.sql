/*
===============================================================================
Migration No : 069
Version      : V069
Title        : Target Topology

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
A SYSTEM says whether it is one server (STANDALONE) or a cluster (CLUSTER), so
the target command can refuse a cluster member added to a single server.
Existing systems: Patroni or more than one active node is CLUSTER, the rest
STANDALONE. A system name, or the name of a server with no system, is unique
among active targets (case-insensitive): commands find systems by name.
===============================================================================
*/


/*
Design notes (2026-11-19, Hasan)
--------------------------------
- First clean install: a target could be defined only by SQL; the target
  command (repository.tools.target) replaces it.
- One shape for a single server: SYSTEM + one NODE, as clusters and offline
  import. The command never asks for a node; the user sees one entry.
- Older single servers defined as a NODE with no SYSTEM (lab pg15-lab,
  pg16-off) keep working; they have no topology.
- Topology is stated, not counted from nodes: a cluster whose members are not
  yet added is still a cluster.
===============================================================================
*/


ALTER TABLE keystone.target
    ADD COLUMN topology VARCHAR(20),
    ADD CONSTRAINT ck_target_topology
        CHECK (topology IN ('STANDALONE', 'CLUSTER')),
    ADD CONSTRAINT ck_target_topology_system
        CHECK (topology IS NULL OR target_type = 'SYSTEM');

COMMENT ON COLUMN keystone.target.topology IS
    'SYSTEM only: STANDALONE (one server) or CLUSTER (members are its NODE targets).';


UPDATE keystone.target s
SET topology = CASE
        WHEN s.cluster_manager = 'PATRONI'
          OR (SELECT count(*) FROM keystone.target n
              WHERE n.parent_target_id = s.target_id
                AND n.target_type = 'NODE' AND n.is_active) > 1
        THEN 'CLUSTER'
        ELSE 'STANDALONE'
    END
WHERE s.target_type = 'SYSTEM';


CREATE UNIQUE INDEX ux_target_active_top_level_name
    ON keystone.target (lower(name))
    WHERE is_active AND parent_target_id IS NULL;
