/*
===============================================================================
Migration No : 066
Version      : V066

Title        : WAL and Tablespace Disk Usage
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-CAP-003 WAL and Tablespace Disk Usage (PG_CAPACITY_HEALTH): how full
the filesystems PostgreSQL writes to besides the data directory's are; pg_wal
moved to its own disk (host collector, provider migration PG029) and
tablespaces outside the data directory (new collector PG_TABLESPACES).
===============================================================================
*/


/*
Design notes (2026-11-14, Hasan)
--------------------------------
- Same limits as PG-CAP-001 (80 % WARNING, 90 % CRITICAL); a mount that is
  also the data directory's is left to PG-CAP-001, so nothing is said twice.
- pg_wal is usually a symbolic link (Linux) or a junction (Windows) inside
  the data directory, which only the postgres user may enter. The host script
  reads the link directly when it can, else with sudo -n only if a sudoers
  rule allows exactly that readlink; no password is ever asked and nothing
  is changed. When it cannot be read the node is not assessed and the report
  gives the three ways with their risks: a sudoers rule for that one command
  (recommended), SSH as postgres, or group access to the data directory
  (not recommended). The customer picks; the next report reads it.
- Tablespace directories come from pg_tablespace_location, readable by any
  role; they are judged even when pg_wal is not known.
- Neither on another disk: NOT_APPLICABLE, PG-CAP-001 covers the one disk.
- Texts: IMPACT says what happens now and if it goes on; RECOMMENDATION ends
  with what the fix costs.
===============================================================================
*/


INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, 'PG-CAP-003', 'WAL and Tablespace Disk Usage',
       'Detects filesystems holding pg_wal or tablespaces, apart from the data directory''s, filled beyond the thresholds.',
       'PG_HOST_SNAPSHOT', NULL,
       'The disk {mount_point} on {node_name} holding {uses} is {used_percent}% full.',
       'Find what fills the disk (WAL kept by slots, replicas or failing archiving; tablespace growth) and plan more capacity.',
       'STORAGE'
FROM keystone.assessment_definition ad
WHERE ad.assessment_key = 'PG_CAPACITY_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, 'PERCENT'
FROM keystone.rule_definition rd
CROSS JOIN (VALUES ('WARNING', 80), ('CRITICAL', 90)) AS t (severity, threshold_value)
WHERE rd.rule_key = 'PG-CAP-003'
ON CONFLICT (rule_id, severity) DO NOTHING;

-- Usage must be recent, like PG-CAP-001; directories rarely change.
INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, TRUE, r.max_age_seconds
FROM keystone.rule_definition rd
CROSS JOIN (VALUES ('PG_HOST_SNAPSHOT', 3600),
                   ('PG_CONFIGURATION_SNAPSHOT', 86400),
                   ('PG_TABLESPACES', 86400)) AS r (evidence_source, max_age_seconds)
WHERE rd.rule_key = 'PG-CAP-003'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
CROSS JOIN (VALUES ('CAPACITY'), ('AVAILABILITY')) AS c (category_key)
WHERE rd.rule_key = 'PG-CAP-003'
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-CAP-003', 'tr', 'NAME', 'WAL ve tablespace diski doluluğu'),
('PG-CAP-003', 'tr', 'HEALTHY', 'pg_wal''ın ya da tablespace''lerin bulunduğu ayrı disklerin hiçbiri {warning} doluluk sınırına ulaşmamış.'),
('PG-CAP-003', 'tr', 'MEANING', 'PostgreSQL''in veri dizini dışında yazdığı bir disk (ayrı diske taşınmış pg_wal ya da bir tablespace) dolmaya yaklaşıyor.'),
('PG-CAP-003', 'tr', 'CAUSES', E'- WAL birikiyor: kullanılmayan replication slot, geride kalan replica ya da başarısız WAL arşivleme\n- max_wal_size ya da wal_keep_size diskin boyutuna göre büyük\n- Tablespace''teki tablolar ve index''ler büyüyor ya da şişkinlik (bloat) temizlenmiyor\n- Aynı diske log ya da yedek dosyaları yazılıyor'),
('PG-CAP-003', 'tr', 'IMPACT', E'Şimdi: diskte kalan alan azalıyor; veri diski boş olsa bile bu disk dolunca PostgreSQL etkilenir.\nBöyle devam ederse: pg_wal diski dolarsa PostgreSQL yeni WAL yazamaz ve kendini kapatır (PANIC), bütün yazma işlemleri durur; tablespace diski dolarsa o tablespace''teki tablolara yazan işlemler hata alır.'),
('PG-CAP-003', 'tr', 'RECOMMENDATION', E'- pg_wal diskinde: pg_replication_slots''ta aktif olmayan ya da çok WAL tutan slot var mı, replica''lar geride mi, arşivleme hata veriyor mu bakın (PG-REP ve PG-BKP bulguları); pg_wal içindeki dosyaları elle silmeyin\n- Tablespace diskinde: en büyük tablo ve index''leri belirleyin; şişkinliği (PG-MAINT-004) ve gereksiz verileri temizleyin\n- Aynı diske yazılan log ya da yedek dosyalarını başka diske alın\n- Büyüme sürüyorsa diski büyütün ya da tabloları ALTER TABLE ... SET TABLESPACE ile başka bir tablespace''e taşıyın\n- Bedeli: slot silmek ya da arşivlemeyi düzeltmek kesinti istemez ama silinen slot''un replica''sı yeniden kurulmak zorunda kalabilir; disk büyütmek çoğu sanal ortamda kesintisizdir; SET TABLESPACE tabloyu taşırken kilitler ve bakım penceresi ister.'),
('PG-CAP-003', 'tr', 'FINDING', '{node_name} üzerinde {uses} bulunan {mount_point} diski %{used_percent} dolu.'),
('PG-CAP-003', 'en', 'NAME', 'WAL and tablespace disk usage'),
('PG-CAP-003', 'en', 'HEALTHY', 'None of the separate disks holding pg_wal or tablespaces has reached the {warning} usage limit.'),
('PG-CAP-003', 'en', 'MEANING', 'A disk PostgreSQL writes to besides the data directory (pg_wal moved to its own disk, or a tablespace) is filling up.'),
('PG-CAP-003', 'en', 'CAUSES', E'- WAL accumulates: an unused replication slot, a lagging replica or failing WAL archiving\n- max_wal_size or wal_keep_size is large for the disk\n- Tables and indexes in the tablespace grow or bloat is not cleaned up\n- Log or backup files are written to the same disk'),
('PG-CAP-003', 'en', 'IMPACT', E'Now: the free space on the disk is shrinking; even with a free data disk, PostgreSQL is affected when this one fills.\nIf it goes on: when the pg_wal disk is full PostgreSQL cannot write WAL and shuts down (PANIC), every write stops; when a tablespace disk is full, writes to tables in that tablespace fail.'),
('PG-CAP-003', 'en', 'RECOMMENDATION', E'- On the pg_wal disk: look in pg_replication_slots for inactive slots or slots holding much WAL, for lagging replicas and failing archiving (PG-REP and PG-BKP findings); never delete files in pg_wal by hand\n- On a tablespace disk: find the largest tables and indexes; clean up bloat (PG-MAINT-004) and data no longer needed\n- Move log or backup files written to the same disk elsewhere\n- If growth continues, grow the disk or move tables to another tablespace with ALTER TABLE ... SET TABLESPACE\n- Cost: dropping a slot or fixing archiving needs no downtime, but the replica of a dropped slot may have to be rebuilt; growing a disk is online on most virtual platforms; SET TABLESPACE locks the table while moving it and needs a maintenance window.'),
('PG-CAP-003', 'en', 'FINDING', 'The disk {mount_point} on {node_name} holding {uses} is {used_percent}% full.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
