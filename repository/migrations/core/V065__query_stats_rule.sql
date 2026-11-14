/*
===============================================================================
Migration No : 065
Version      : V065

Title        : Most Expensive Queries
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-PERF-001 Most Expensive Queries (PG_PERFORMANCE_HEALTH) on the new
collector PG_QUERY_STATS (provider migration PG028): whether
pg_stat_statements can be read, and how to set it up when it cannot. The
statements themselves are a report section, not findings.
===============================================================================
*/


/*
Design notes (2026-11-14, Hasan)
--------------------------------
- Context, not a finding: a statement taking most of the time can be the
  system's main work. The report shows the 10 statements with the most time
  and, on PG-CAP-005 and PG-PERF-002 findings, the statements of that database
  writing most temporary files or reading most from disk.
- pg_stat_statements is the most used extension: Keystone recommends it and
  gives the steps (shared_preload_libraries, restart, CREATE EXTENSION in the
  database Keystone reads); the customer acts. Not loaded or not created:
  NOT_APPLICABLE with the steps. Not readable: INSUFFICIENT_EVIDENCE with the
  grant.
- Totals since pg_stat_statements was reset (pg_stat_statements_info, 14+);
  windows per statement are later work.
===============================================================================
*/


INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, 'PG-PERF-001', 'Most Expensive Queries',
       'Reads the most expensive statements from pg_stat_statements for the report; says how to set it up when it is missing.',
       'PG_QUERY_STATS', NULL,
       'pg_stat_statements can be read.',
       'Look at the most expensive statements in the report section.', 'PERFORMANCE'
FROM keystone.assessment_definition ad
WHERE ad.assessment_key = 'PG_PERFORMANCE_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rule_id, 'PG_QUERY_STATS', TRUE, 3600
FROM keystone.rule_definition WHERE rule_key = 'PG-PERF-001'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rule_id, 'PERFORMANCE'
FROM keystone.rule_definition WHERE rule_key = 'PG-PERF-001'
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-PERF-001', 'tr', 'NAME', 'En pahalı sorgular'),
('PG-PERF-001', 'tr', 'HEALTHY', 'pg_stat_statements okunabiliyor; en çok süre harcayan sorgular raporun "En pahalı sorgular" bölümünde.'),
('PG-PERF-001', 'tr', 'MEANING', 'Sorgu istatistikleri (pg_stat_statements) hangi sorguların veritabanının zamanını en çok harcadığını gösterir; bu bir bulgu değil, yavaşlık, disk okuması ya da geçici dosya bulgularında "hangi sorgu" sorusunun cevabıdır.'),
('PG-PERF-001', 'tr', 'CAUSES', E'- pg_stat_statements shared_preload_libraries''a eklenmemiş (restart gerektirdiği için ertelenmiş olabilir)\n- Yüklü ama Keystone''un bağlandığı veritabanında CREATE EXTENSION yapılmamış'),
('PG-PERF-001', 'tr', 'IMPACT', E'Şimdi: yavaşlık ya da disk baskısı bulgularında sebep olan sorgular adıyla gösterilemez.\nBöyle devam ederse: her performans sorununda hangi sorgunun sorumlu olduğu sonradan tahminle bulunmaya çalışılır.'),
('PG-PERF-001', 'tr', 'RECOMMENDATION', E'- shared_preload_libraries''a pg_stat_statements ekleyin (Patroni''de parameters altında) ve restart edin\n- Keystone''un bağlandığı veritabanında: CREATE EXTENSION pg_stat_statements;\n- Bedeli: tek seferlik restart; ek yük çok küçüktür.'),
('PG-PERF-001', 'tr', 'FINDING', 'pg_stat_statements okunabiliyor.'),
('PG-PERF-001', 'en', 'NAME', 'Most expensive queries'),
('PG-PERF-001', 'en', 'HEALTHY', 'pg_stat_statements can be read; the statements taking the most time are in the report section "Most expensive queries".'),
('PG-PERF-001', 'en', 'MEANING', 'Query statistics (pg_stat_statements) show which statements take most of the database''s time; not a finding, but the answer to "which query" for slowness, disk read and temporary file findings.'),
('PG-PERF-001', 'en', 'CAUSES', E'- pg_stat_statements is not in shared_preload_libraries (it needs a restart, which may have been postponed)\n- It is loaded but CREATE EXTENSION was not run in the database Keystone connects to'),
('PG-PERF-001', 'en', 'IMPACT', E'Now: findings on slowness or disk pressure cannot name the statements causing them.\nIf it goes on: every performance problem is traced back to a statement by guesswork.'),
('PG-PERF-001', 'en', 'RECOMMENDATION', E'- Add pg_stat_statements to shared_preload_libraries (under parameters in Patroni) and restart\n- In the database Keystone connects to: CREATE EXTENSION pg_stat_statements;\n- Cost: one restart; the overhead is very small.'),
('PG-PERF-001', 'en', 'FINDING', 'pg_stat_statements can be read.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
