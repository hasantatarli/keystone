/*
===============================================================================
Migration No : 039
Version      : V039
Title        : Rule Parameters and Maintenance Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds keystone.rule_parameter (named preconditions and limits besides the
severity thresholds) and assessment_result.parameters_used; adds
PG_MAINTENANCE_HEALTH with PG-MAINT-001 Dead Tuple Pressure and PG-MAINT-002
Stale Statistics.
===============================================================================
*/


/*
Design notes (2026-10-26, Hasan)
--------------------------------
Severity still comes from rule_threshold on the rule's main metric. Any number
of named parameters can be attached to a rule; the evaluator combines them in
code. A generic rule expression language stays rejected (2026-10-05).

PG-MAINT-001 / -002 are judged per table:
- ratio at or above the WARNING / CRITICAL threshold -> that severity;
- ratio below, but the count beyond the large-table limit -> WARNING
  (20 % of a billion-row table is already a large problem);
- below the minimum count the table is not judged (small tables).
Defaults follow PostgreSQL's autovacuum scale factors (vacuum 20 %, analyze
10 %): a finding means autovacuum is behind.
===============================================================================
*/


/* ============================================================================
   RULE PARAMETERS
   ============================================================================ */

CREATE TABLE keystone.rule_parameter
(
    rule_id          BIGINT         NOT NULL,
    parameter_key    VARCHAR(64)    NOT NULL,
    parameter_value  NUMERIC(20,4)  NOT NULL,
    parameter_unit   VARCHAR(30)    NOT NULL,
    description      TEXT,

    CONSTRAINT pk_rule_parameter PRIMARY KEY (rule_id, parameter_key),
    CONSTRAINT fk_rule_parameter_rule
        FOREIGN KEY (rule_id) REFERENCES keystone.rule_definition (rule_id)
);

COMMENT ON TABLE keystone.rule_parameter IS
'Named preconditions and limits of a rule besides its severity thresholds; combined by the rule''s evaluator.';

ALTER TABLE keystone.assessment_result
    ADD COLUMN parameters_used JSONB;

COMMENT ON COLUMN keystone.assessment_result.parameters_used IS
'Rule parameters applied when the rule was evaluated: {"key": {"value", "unit"}}. NULL for rules without parameters.';


/* ============================================================================
   ASSESSMENT AND RULES
   ============================================================================ */

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_MAINTENANCE_HEALTH', 'Maintenance Health', 'PostgreSQL',
     'Evaluates whether vacuum and analyze keep tables clean and statistics current.', 3600)
ON CONFLICT (assessment_key) DO NOTHING;

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, 'PG_VACUUM_ANALYZE', NULL,
       r.finding_template, r.recommendation, 'MAINTENANCE'
FROM keystone.assessment_definition ad
CROSS JOIN (VALUES
    ('PG-MAINT-001', 'Dead Tuple Pressure',
     'Detects tables whose dead rows are a large share of all rows, or very many in a large table.',
     'Table {table} has {dead_rows} dead rows ({percent}% of all rows).',
     'Find out why autovacuum does not keep up with this table: long transactions, a too high autovacuum_vacuum_scale_factor for its size, or too few autovacuum workers. Run a manual VACUUM if needed.'),
    ('PG-MAINT-002', 'Stale Statistics',
     'Detects tables with many rows changed since their last analyze.',
     'Table {table} has {modified_rows} rows changed since its last analyze ({percent}% of live rows).',
     'Run ANALYZE on the table and lower autovacuum_analyze_scale_factor for large, frequently changed tables.')
) AS r (rule_key, name, description, finding_template, recommendation)
WHERE ad.assessment_key = 'PG_MAINTENANCE_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   THRESHOLDS, PARAMETERS, EVIDENCE, CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, 'PERCENT'
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-MAINT-001', 'WARNING',  20),
    ('PG-MAINT-001', 'CRITICAL', 40),
    ('PG-MAINT-002', 'WARNING',  20),
    ('PG-MAINT-002', 'CRITICAL', 50)
) AS t (rule_key, severity, threshold_value) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rd.rule_id, p.parameter_key, p.parameter_value, 'ROW', p.description
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-MAINT-001', 'min_dead_tuples',           10000,
     'Tables with fewer dead rows are not judged.'),
    ('PG-MAINT-001', 'large_table_dead_tuples',   50000000,
     'At least WARNING from this many dead rows, whatever the ratio.'),
    ('PG-MAINT-002', 'min_modifications',         10000,
     'Tables with fewer changed rows are not judged.'),
    ('PG-MAINT-002', 'large_table_modifications', 50000000,
     'At least WARNING from this many changed rows, whatever the ratio.')
) AS p (rule_key, parameter_key, parameter_value, description) ON p.rule_key = rd.rule_key
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rule_id, 'PG_VACUUM_ANALYZE', TRUE, 86400
FROM keystone.rule_definition
WHERE rule_key IN ('PG-MAINT-001', 'PG-MAINT-002')
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-MAINT-001', 'PERFORMANCE'),
    ('PG-MAINT-001', 'CAPACITY'),
    ('PG-MAINT-002', 'PERFORMANCE')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-MAINT-001 --------------------------------------------------------------
('PG-MAINT-001', 'tr', 'NAME', 'Dead tuple birikmesi'),
('PG-MAINT-001', 'tr', 'HEALTHY', 'Hiçbir tabloda dead tuple oranı {warning} sınırına ulaşmamış.'),
('PG-MAINT-001', 'tr', 'MEANING', 'Bazı tablolarda silinen ve güncellenen satırların eski sürümleri (dead tuple) temizlenmeden birikmiş.'),
('PG-MAINT-001', 'tr', 'CAUSES', E'- Autovacuum bu tabloya yetişemiyor (tablo boyutuna göre autovacuum_vacuum_scale_factor yüksek)\n- Uzun süren transaction''lar ya da replication slot''lar vacuum''un temizlemesini engelliyor\n- Autovacuum worker sayısı ya da cost limit ayarı yetersiz\n- Tabloda autovacuum kapatılmış'),
('PG-MAINT-001', 'tr', 'IMPACT', 'Tablo ve index''ler şişer: disk kullanımı artar, sorgular gereksiz satırları da okuyup yavaşlar. Temizlik geciktikçe vacuum daha uzun sürer.'),
('PG-MAINT-001', 'tr', 'RECOMMENDATION', E'- Vacuum''u engelleyen uzun transaction ya da slot olup olmadığını kontrol edin\n- Büyük ve sık değişen tablolar için autovacuum_vacuum_scale_factor değerini tablo bazında düşürün\n- Gerekirse tabloyu yoğun olmayan bir saatte elle VACUUM edin\n- Autovacuum worker ve cost limit ayarlarını gözden geçirin'),
('PG-MAINT-001', 'en', 'NAME', 'Dead tuple pressure'),
('PG-MAINT-001', 'en', 'HEALTHY', 'No table has reached a dead tuple ratio of {warning}.'),
('PG-MAINT-001', 'en', 'MEANING', 'Old versions of deleted and updated rows (dead tuples) have piled up in some tables without being cleaned up.'),
('PG-MAINT-001', 'en', 'CAUSES', E'- Autovacuum cannot keep up with the table (autovacuum_vacuum_scale_factor too high for its size)\n- Long transactions or replication slots stop vacuum from removing rows\n- Too few autovacuum workers or too low a cost limit\n- Autovacuum is disabled for the table'),
('PG-MAINT-001', 'en', 'IMPACT', 'Tables and indexes bloat: disk usage grows and queries slow down because they also read rows that are no longer needed. The longer cleanup waits, the longer vacuum takes.'),
('PG-MAINT-001', 'en', 'RECOMMENDATION', E'- Check for long transactions or slots that block vacuum\n- Lower autovacuum_vacuum_scale_factor per table for large, frequently changed tables\n- If needed, VACUUM the table by hand at a quiet time\n- Review autovacuum worker and cost limit settings'),

-- PG-MAINT-002 --------------------------------------------------------------
('PG-MAINT-002', 'tr', 'NAME', 'Eski istatistikler'),
('PG-MAINT-002', 'tr', 'HEALTHY', 'Hiçbir tabloda son ANALYZE''dan beri değişen satır oranı {warning} sınırına ulaşmamış.'),
('PG-MAINT-002', 'tr', 'MEANING', 'Bazı tablolarda son ANALYZE''dan bu yana çok sayıda satır değişmiş; planner''ın kullandığı istatistikler tablonun bugünkü haliyle uyuşmuyor.'),
('PG-MAINT-002', 'tr', 'CAUSES', E'- Büyük tablolarda autovacuum_analyze_scale_factor yüksek kalmış\n- Toplu yükleme ya da silme sonrasında ANALYZE çalıştırılmamış\n- Autovacuum yetişemiyor ya da tabloda kapatılmış'),
('PG-MAINT-002', 'tr', 'IMPACT', 'Planner satır sayılarını yanlış tahmin eder ve kötü plan seçebilir: sorgular aniden yavaşlayabilir, gereksiz yere tam tablo taraması yapılabilir.'),
('PG-MAINT-002', 'tr', 'RECOMMENDATION', E'- Tabloda ANALYZE çalıştırın\n- Büyük ve sık değişen tablolar için autovacuum_analyze_scale_factor değerini tablo bazında düşürün\n- Toplu yükleme ve silme işlerinin sonuna ANALYZE ekleyin'),
('PG-MAINT-002', 'en', 'NAME', 'Stale statistics'),
('PG-MAINT-002', 'en', 'HEALTHY', 'No table has reached a ratio of {warning} rows changed since its last analyze.'),
('PG-MAINT-002', 'en', 'MEANING', 'Many rows of some tables changed since their last ANALYZE; the statistics the planner uses no longer match the tables.'),
('PG-MAINT-002', 'en', 'CAUSES', E'- autovacuum_analyze_scale_factor is too high for large tables\n- ANALYZE was not run after a bulk load or delete\n- Autovacuum cannot keep up or is disabled for the table'),
('PG-MAINT-002', 'en', 'IMPACT', 'The planner misjudges row counts and can choose bad plans: queries can suddenly slow down or scan whole tables needlessly.'),
('PG-MAINT-002', 'en', 'RECOMMENDATION', E'- Run ANALYZE on the table\n- Lower autovacuum_analyze_scale_factor per table for large, frequently changed tables\n- Add ANALYZE to the end of bulk load and delete jobs')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
