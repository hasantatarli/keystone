/*
===============================================================================
Migration No : 064
Version      : V064

Title        : Table and Index Bloat Rule
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-MAINT-004 Table and Index Bloat (PG_MAINTENANCE_HEALTH) on the new
collector PG_TABLE_BLOAT (provider migration PG027): estimated wasted space
of tables and btree indexes, WARNING only.
===============================================================================
*/


/*
Design notes (2026-11-14, Hasan)
--------------------------------
- Estimated, not measured: pgstattuple (exact) reads the whole table; not on
  a customer's system. Two estimates, in order: pgstattuple_approx when the
  extension is installed (pg_monitor may run it); otherwise column widths
  from pg_stats, which shows a table's columns only to a role that may SELECT
  it (offline collection as postgres: yes; Keystone's role: no).
- Neither available: not assessed, and both ways are offered with their
  risks; the customer picks (Hasan): install pgstattuple, or SELECT on the
  tables / pg_read_all_data, which also lets the role read the data.
- WARNING when wasted >= 30 % and >= 1 GB; no CRITICAL for an estimate.
- Texts: IMPACT says what happens now and if it goes on; RECOMMENDATION ends
  with what the fix costs.
===============================================================================
*/


INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, 'PG-MAINT-004', 'Table and Index Bloat',
       'Detects tables and btree indexes with a large share of estimated wasted space.',
       'PG_TABLE_BLOAT', NULL,
       '{kind} {object} in database {database_name}: about {wasted_bytes} of {size_bytes} bytes ({share}%) is estimated wasted space.',
       'Reclaim the space with pg_repack, or VACUUM FULL / REINDEX in a maintenance window.', 'MAINTENANCE'
FROM keystone.assessment_definition ad
WHERE ad.assessment_key = 'PG_MAINTENANCE_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rule_id, 'WARNING', 30, 'PERCENT'
FROM keystone.rule_definition WHERE rule_key = 'PG-MAINT-004'
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rule_id, 'min_wasted', 1073741824, 'BYTE', 'Objects wasting less than this are not reported.'
FROM keystone.rule_definition WHERE rule_key = 'PG-MAINT-004'
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rule_id, 'PG_TABLE_BLOAT', TRUE, 86400
FROM keystone.rule_definition WHERE rule_key = 'PG-MAINT-004'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES ('PG-MAINT-004', 'PERFORMANCE'), ('PG-MAINT-004', 'CAPACITY')) AS c (rule_key, category_key)
    ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-MAINT-004', 'tr', 'NAME', 'Tablo ve index şişmesi (bloat)'),
('PG-MAINT-004', 'tr', 'HEALTHY', 'Hiçbir tablo ya da index''te tahmini boş alan {warning} ve 1 GB sınırını aşmıyor.'),
('PG-MAINT-004', 'tr', 'MEANING', 'Tablo ya da index''in diskte kapladığı alanın önemli bir kısmı silinmiş ya da güncellenmiş satırlardan kalan boş alan; bu bir tahmindir (pgstattuple_approx ya da kolon istatistiklerinden), kesin ölçüm değildir.'),
('PG-MAINT-004', 'tr', 'CAUSES', E'- Büyük toplu DELETE ya da UPDATE sonrası boşalan alan geri verilmedi (VACUUM alanı yeniden kullanıma açar ama diske iade etmez)\n- Autovacuum uzun süre yetişemedi ya da uzun açık kalan transaction''lar temizliği engelledi\n- Sık güncellenen index''ler zamanla seyrekleşti'),
('PG-MAINT-004', 'tr', 'IMPACT', E'Şimdi: sorgular boş sayfaları da okur; tam taramalar ve index taramaları gerekenden yavaş çalışır, bellekteki önbellek boş alanla dolar, yedekler ve replikasyon gereksiz büyür.\nBöyle devam ederse: alan yeniden kullanılmadıkça şişme kalıcıdır; tablo büyüdükçe boşa giden disk ve okuma maliyeti de büyür.'),
('PG-MAINT-004', 'tr', 'RECOMMENDATION', E'- Önce tahmini doğrulayın: pgstattuple kuruluysa SELECT * FROM pgstattuple(''<tablo>''); (tabloyu baştan sona okur, yoğun saatte çalıştırmayın)\n- Tablo için: pg_repack (tabloyu kilitlemeden yeniden yazar; extension kurulumu ister) ya da bakım penceresinde VACUUM FULL (tabloyu yazma ve okumaya kilitler)\n- Index için: REINDEX INDEX CONCURRENTLY <index>; (PostgreSQL 12+, kilitlemez)\n- Tekrarı önlemek için autovacuum''un yetişip yetişmediğine ve uzun açık transaction''lara bakın\n- Bedeli: pg_repack ve REINDEX CONCURRENTLY kesinti gerektirmez ama işlem süresince tablo kadar ek disk alanı ister; VACUUM FULL tabloyu süresince erişilemez yapar.'),
('PG-MAINT-004', 'tr', 'FINDING', '{database_name} veritabanındaki {object} ({kind}) için {size_bytes} alanın yaklaşık {wasted_bytes} kadarı (%{share}) boş alan olarak tahmin ediliyor.'),
('PG-MAINT-004', 'en', 'NAME', 'Table and index bloat'),
('PG-MAINT-004', 'en', 'HEALTHY', 'No table or index has estimated wasted space above {warning} and 1 GB.'),
('PG-MAINT-004', 'en', 'MEANING', 'A large share of the space a table or index takes on disk is left free by deleted or updated rows; this is an estimate (pgstattuple_approx or column statistics), not a measurement.'),
('PG-MAINT-004', 'en', 'CAUSES', E'- Space freed by a large DELETE or UPDATE was not given back (VACUUM makes it reusable but does not return it to the disk)\n- Autovacuum fell behind for long, or long open transactions held back the cleanup\n- Frequently updated indexes became sparse over time'),
('PG-MAINT-004', 'en', 'IMPACT', E'Now: queries read the empty pages too; full scans and index scans take longer than needed, the cache fills with free space, backups and replication grow for nothing.\nIf it goes on: unless the space is reused, the bloat stays; as the table grows, so do the wasted disk and read cost.'),
('PG-MAINT-004', 'en', 'RECOMMENDATION', E'- First confirm the estimate: with pgstattuple, SELECT * FROM pgstattuple(''<table>''); (reads the whole table; not at busy hours)\n- A table: pg_repack (rewrites it without locking; needs the extension) or VACUUM FULL in a maintenance window (locks the table for reads and writes)\n- An index: REINDEX INDEX CONCURRENTLY <index>; (PostgreSQL 12+, no lock)\n- To prevent it, check whether autovacuum keeps up and look for long open transactions\n- Cost: pg_repack and REINDEX CONCURRENTLY need no downtime but as much extra disk as the object while they run; VACUUM FULL makes the table unavailable while it runs.'),
('PG-MAINT-004', 'en', 'FINDING', 'In database {database_name}, about {wasted_bytes} of {size_bytes} ({share}%) of {object} ({kind}) is estimated wasted space.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
