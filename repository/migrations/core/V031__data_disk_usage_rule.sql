/*
===============================================================================
Migration No : 031
Version      : V031
Title        : Data Disk Usage Rule

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the PG_CAPACITY_HEALTH assessment, the STORAGE topic and the first
capacity rule PG-CAP-001 Data Disk Usage: how full the filesystem holding
PostgreSQL's data_directory is, on every node.
===============================================================================
*/


/*
Design notes (2026-10-20)
-------------------------
The first report showed disk usage in the inventory while "Capacity" said
"no problems": a judgement outside the rules contradicted the rule summary.
Judgements are rules; the inventory only displays.

Evidence comes from two NODE-scoped collectors: PG_HOST_SNAPSHOT (filesystem
capacity, SSH) and PG_CONFIGURATION_SNAPSHOT (data_directory). The data disk
is the mount with the longest mount point containing data_directory. Without
host access the rule ends INSUFFICIENT_EVIDENCE; it never guesses.

Known limitations: tablespaces and a separately mounted pg_wal are not
evaluated yet; nodes without host evidence are not evaluated while other nodes
are (the report inventory shows them as unknown).
===============================================================================
*/


/* ============================================================================
   TOPIC
   ============================================================================ */

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('STORAGE', 50)
ON CONFLICT (topic_key) DO NOTHING;

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name) VALUES
    ('STORAGE', 'tr', 'Depolama'),
    ('STORAGE', 'en', 'Storage')
ON CONFLICT (topic_key, language_code) DO NOTHING;


/* ============================================================================
   ASSESSMENT
   ============================================================================ */

INSERT INTO keystone.assessment_definition
(
    assessment_key,
    name,
    provider,
    description,
    default_interval_seconds
)
VALUES
(
    'PG_CAPACITY_HEALTH',
    'Capacity Health',
    'PostgreSQL',
    'Evaluates storage and resource capacity of PostgreSQL nodes for conditions that may stop or slow down the database.',
    900
)
ON CONFLICT (assessment_key) DO NOTHING;


/* ============================================================================
   RULE DEFINITION
   ============================================================================ */

INSERT INTO keystone.rule_definition
(
    assessment_id,
    rule_key,
    name,
    description,
    evidence_source,
    default_severity,
    finding_template,
    recommendation,
    topic_key
)
SELECT
    assessment_id,
    'PG-CAP-001',
    'Data Disk Usage',
    'Detects nodes whose filesystem holding data_directory is filled beyond the configured thresholds.',
    'PG_HOST_SNAPSHOT',
    NULL,
    'The data disk {mount_point} on {node_name} is {used_percent}% full (data_directory {data_directory}).',
    'Find what uses the space: database and table sizes, the pg_wal directory, log and backup files on the same disk. Remove what is not needed in the short term and plan more capacity if growth continues. Check that no replication slot is retaining WAL.',
    'STORAGE'
FROM keystone.assessment_definition
WHERE assessment_key = 'PG_CAPACITY_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   RULE THRESHOLDS
   ============================================================================ */

INSERT INTO keystone.rule_threshold
(
    rule_id,
    severity,
    threshold_value,
    threshold_unit
)
SELECT
    rd.rule_id,
    t.severity,
    t.threshold_value,
    t.threshold_unit
FROM keystone.rule_definition AS rd
CROSS JOIN
(
    VALUES
        ('WARNING',  80, 'PERCENT'),
        ('CRITICAL', 90, 'PERCENT')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-CAP-001'
ON CONFLICT (rule_id, severity) DO NOTHING;


/* ============================================================================
   EVIDENCE REQUIREMENTS
   ============================================================================ */

-- data_directory rarely changes; filesystem usage must be recent.
INSERT INTO keystone.rule_evidence_requirement
(
    rule_id,
    evidence_source,
    is_required,
    max_age_seconds
)
SELECT rd.rule_id, r.evidence_source, TRUE, r.max_age_seconds
FROM keystone.rule_definition rd
CROSS JOIN
(
    VALUES
        ('PG_HOST_SNAPSHOT',          3600),
        ('PG_CONFIGURATION_SNAPSHOT', 86400)
) AS r (evidence_source, max_age_seconds)
WHERE rd.rule_key = 'PG-CAP-001'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;


/* ============================================================================
   IMPACT CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-CAP-001', 'CAPACITY'),
    ('PG-CAP-001', 'AVAILABILITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-CAP-001', 'tr', 'NAME', 'Veri diski doluluğu'),
('PG-CAP-001', 'tr', 'HEALTHY',
 'Hiçbir sunucunun veri diski {warning} doluluk sınırına ulaşmamış.'),
('PG-CAP-001', 'tr', 'MEANING',
 'PostgreSQL''in veri dizininin (data_directory) bulunduğu disk dolmaya yaklaşıyor. Sebep genellikle veritabanının büyümesi, temizlenmeyen şişkinlik (bloat), biriken WAL dosyaları ya da aynı diskte tutulan log ve yedek dosyalarıdır.'),
('PG-CAP-001', 'tr', 'IMPACT',
 'Disk dolduğunda PostgreSQL yeni veri yazamaz: işlemler hata alır ve veritabanı durabilir. Dolmaya yakın bir diskte vacuum ve index bakımı gibi geçici alan isteyen işlemler de başarısız olabilir.'),
('PG-CAP-001', 'tr', 'RECOMMENDATION',
 'Diskte yer kaplayan şeyleri belirleyin: veritabanı ve tablo boyutları, pg_wal dizini, aynı diskteki log ve yedek dosyaları. Kısa vadede gereksiz dosyaları temizleyin; büyüme sürüyorsa disk kapasitesini artırmayı planlayın. Replication slot''larının WAL biriktirmediğini de kontrol edin.'),
('PG-CAP-001', 'en', 'NAME', 'Data disk usage'),
('PG-CAP-001', 'en', 'HEALTHY',
 'No server''s data disk has reached the {warning} usage limit.'),
('PG-CAP-001', 'en', 'MEANING',
 'The disk holding PostgreSQL''s data directory (data_directory) is filling up. The usual causes are database growth, bloat that is not cleaned up, accumulating WAL files, or log and backup files kept on the same disk.'),
('PG-CAP-001', 'en', 'IMPACT',
 'When the disk is full PostgreSQL cannot write: transactions fail and the database can stop. On a nearly full disk, work that needs temporary space, such as vacuum and index maintenance, can fail too.'),
('PG-CAP-001', 'en', 'RECOMMENDATION',
 'Find what uses the space: database and table sizes, the pg_wal directory, log and backup files on the same disk. Remove what is not needed in the short term and plan more capacity if growth continues. Also check that no replication slot is retaining WAL.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
