/*
===============================================================================
Migration No : 057
Version      : V057
Title        : Object Structure Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-IDX-003 Duplicate Index and PG-IDX-004 Foreign Key Without Index
(PG_INDEX_HEALTH), PG-BKP-003 Unlogged Tables (PG_BACKUP_HEALTH) and, in the
new assessment PG_LIFECYCLE_HEALTH with topic LIFECYCLE, PG-LIFE-004
Extension Update Available, on index definitions (PG_INDEX_USAGE) and the new
collectors PG_TABLE_STRUCTURE and PG_EXTENSIONS (provider migration PG022).
===============================================================================
*/


/*
Design notes (2026-11-10, Hasan)
--------------------------------
- PG-IDX-003 reads the primary's indexes (definitions are the same on
  replicas). Same table, method, key and INCLUDE columns, operator classes,
  collations, expressions and predicate: a duplicate, WARNING; the index that
  backs no constraint is reported. A btree index whose key columns are the
  leading key columns of another btree index (same operator classes and
  collations, no expressions, no predicate) is redundant, INFO; unique and
  constraint indexes are never reported as redundant (they enforce a rule).
  Extension-owned and invalid indexes are left out.
- PG-IDX-004: a foreign key whose columns do not lead any valid, non-partial
  index, on a table of at least min_table_size: deleting or updating the
  referenced row scans the table under lock. Smaller tables are not judged.
- PG-BKP-003: unlogged tables are emptied after a crash and not replicated.
  They may be a deliberate choice (caches, staging); the text says so.
- PG-LIFE-004: an extension whose installed version differs from the version
  of the package on the server (pg_available_extensions.default_version).
  ALTER EXTENSION ... UPDATE is enough; no release list is needed. INFO.
===============================================================================
*/


/* ============================================================================
   TOPIC AND ASSESSMENT
   ============================================================================ */

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('LIFECYCLE', 90)
ON CONFLICT (topic_key) DO NOTHING;

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name) VALUES
    ('LIFECYCLE', 'tr', 'Sürüm ve yaşam döngüsü'),
    ('LIFECYCLE', 'en', 'Versions and lifecycle')
ON CONFLICT (topic_key, language_code) DO NOTHING;

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_LIFECYCLE_HEALTH', 'Lifecycle Health', 'PostgreSQL',
     'Evaluates versions of PostgreSQL components that can be updated.',
     86400)
ON CONFLICT (assessment_key) DO NOTHING;


/* ============================================================================
   RULE DEFINITIONS
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source,
       r.default_severity, r.finding_template, r.recommendation, r.topic_key
FROM (VALUES
    ('PG_INDEX_HEALTH', 'PG-IDX-003', 'Duplicate Index',
     'Detects indexes with the same definition as another index of the table, or covered by a longer one.',
     'PG_INDEX_USAGE', 'WARNING',
     'Index {index} on {table} has the same definition as {other}.',
     'Drop the extra index with DROP INDEX CONCURRENTLY after checking that no constraint or query hint needs it.',
     'INDEXES'),
    ('PG_INDEX_HEALTH', 'PG-IDX-004', 'Foreign Key Without Index',
     'Detects foreign keys on large tables without an index starting with their columns.',
     'PG_TABLE_STRUCTURE', 'WARNING',
     'Foreign key {constraint} on {table} ({columns}) referencing {referenced} has no index starting with its columns.',
     'Create an index on the foreign key columns with CREATE INDEX CONCURRENTLY.',
     'INDEXES'),
    ('PG_BACKUP_HEALTH', 'PG-BKP-003', 'Unlogged Tables',
     'Lists unlogged tables: emptied after a crash and not replicated.',
     'PG_TABLE_STRUCTURE', 'WARNING',
     'Table {table} is unlogged ({size_bytes} bytes).',
     'Confirm that losing the table''s contents after a crash and on failover is acceptable; otherwise run ALTER TABLE ... SET LOGGED.',
     'BACKUP'),
    ('PG_LIFECYCLE_HEALTH', 'PG-LIFE-004', 'Extension Update Available',
     'Detects extensions whose installed version differs from the package installed on the server.',
     'PG_EXTENSIONS', 'INFO',
     'Extension {extension} in database {database_name} is at version {installed}; the server has {available}.',
     'Read the extension''s release notes and run ALTER EXTENSION ... UPDATE in a maintenance window.',
     'LIFECYCLE')
) AS r (assessment_key, rule_key, name, description, evidence_source, default_severity,
        finding_template, recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = r.assessment_key
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   PARAMETERS, EVIDENCE, CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rule_id, 'min_table_size', 10485760, 'BYTE',
       'Foreign keys on smaller tables are not judged.'
FROM keystone.rule_definition
WHERE rule_key = 'PG-IDX-004'
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, e.evidence_source, TRUE, 86400
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-003',  'PG_INDEX_USAGE'),
    ('PG-IDX-004',  'PG_TABLE_STRUCTURE'),
    ('PG-BKP-003',  'PG_TABLE_STRUCTURE'),
    ('PG-LIFE-004', 'PG_EXTENSIONS')
) AS e (rule_key, evidence_source) ON e.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-003',  'PERFORMANCE'),
    ('PG-IDX-003',  'CAPACITY'),
    ('PG-IDX-004',  'PERFORMANCE'),
    ('PG-IDX-004',  'AVAILABILITY'),
    ('PG-BKP-003',  'DATA_SAFETY'),
    ('PG-LIFE-004', 'SECURITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
-- PG-IDX-003 ----------------------------------------------------------------
('PG-IDX-003', 'tr', 'NAME', 'Tekrarlanan index'),
('PG-IDX-003', 'tr', 'HEALTHY', 'Aynı tanıma sahip ya da başka bir index tarafından kapsanan index yok.'),
('PG-IDX-003', 'tr', 'MEANING', 'Bazı tablolarda aynı işi yapan birden fazla index var: tanımı birebir aynı olan ya da daha uzun bir index''in ilk kolonlarıyla aynı olan index''ler.'),
('PG-IDX-003', 'tr', 'CAUSES', E'- Aynı index farklı adla, farklı zamanlarda iki kez oluşturuldu\n- Bir migration aracı ya da ORM kendi index''ini ekledi\n- Daha geniş bir index eklendi ama eski, kısa olan kaldırılmadı'),
('PG-IDX-003', 'tr', 'IMPACT', 'Gereksiz index her INSERT, UPDATE ve DELETE''te ayrıca güncellenir; yazmayı yavaşlatır, disk ve bellek tüketir, vacuum''u uzatır. Okumaya bir katkısı yoktur.'),
('PG-IDX-003', 'tr', 'RECOMMENDATION', E'- Fazla olan index''i hiçbir kısıtın ya da sorgu ipucunun kullanmadığını doğrulayın\n- DROP INDEX CONCURRENTLY ile kaldırın; yazma kilidi almaz\n- Kısa index''i kaldırmadan önce uzun index''in aynı sorgulara yettiğini kontrol edin (kısa index daha küçük olduğu için bazı sorgularda tercih edilebilir)'),
('PG-IDX-003', 'tr', 'FINDING', '{table} tablosundaki {index} index''i {other} ile aynı tanıma sahip.'),
('PG-IDX-003', 'tr', 'FINDING_ALT', '{table} tablosundaki {index} index''i, aynı kolonlarla başlayan {other} tarafından kapsanıyor.'),
('PG-IDX-003', 'en', 'NAME', 'Duplicate index'),
('PG-IDX-003', 'en', 'HEALTHY', 'No index has the same definition as another or is covered by a longer one.'),
('PG-IDX-003', 'en', 'MEANING', 'Some tables have more than one index doing the same job: indexes with exactly the same definition, or the same as the first columns of a longer index.'),
('PG-IDX-003', 'en', 'CAUSES', E'- The same index was created twice, under different names, at different times\n- A migration tool or ORM added its own index\n- A wider index was added but the old, shorter one was not dropped'),
('PG-IDX-003', 'en', 'IMPACT', 'An extra index is updated on every INSERT, UPDATE and DELETE; it slows writes, uses disk and memory and makes vacuum longer. It adds nothing to reads.'),
('PG-IDX-003', 'en', 'RECOMMENDATION', E'- Check that no constraint or query hint uses the extra index\n- Drop it with DROP INDEX CONCURRENTLY; it takes no write lock\n- Before dropping a shorter index, check that the longer one serves the same queries (the shorter one is smaller and may be preferred for some)'),
('PG-IDX-003', 'en', 'FINDING', 'Index {index} on {table} has the same definition as {other}.'),
('PG-IDX-003', 'en', 'FINDING_ALT', 'Index {index} on {table} is covered by {other}, which starts with the same columns.'),
-- PG-IDX-004 ----------------------------------------------------------------
('PG-IDX-004', 'tr', 'NAME', 'Index''i olmayan foreign key'),
('PG-IDX-004', 'tr', 'HEALTHY', 'Büyük tablolardaki bütün foreign key''lerin kolonlarıyla başlayan bir index var.'),
('PG-IDX-004', 'tr', 'MEANING', 'Bazı büyük tablolarda foreign key kolonlarıyla başlayan bir index yok.'),
('PG-IDX-004', 'tr', 'CAUSES', E'- PostgreSQL foreign key oluştururken referans veren tarafta index oluşturmaz; elle eklenmesi gerekir\n- Tablo küçükken sorun olmadı, büyüdükçe görünür hale geldi'),
('PG-IDX-004', 'tr', 'IMPACT', 'Referans verilen tablodan bir satır silindiğinde ya da anahtarı güncellendiğinde PostgreSQL bu tabloyu baştan sona tarar; işlem yavaşlar ve bu sürede tutulan kilitler diğer işlemleri bekletebilir. Bu kolonlarla yapılan join''ler de yavaştır.'),
('PG-IDX-004', 'tr', 'RECOMMENDATION', E'- Foreign key kolonlarına CREATE INDEX CONCURRENTLY ile index ekleyin\n- Kolonları foreign key''deki sırayla yazın; mevcut bir index''in başına eklemek de yeterli olabilir'),
('PG-IDX-004', 'tr', 'FINDING', '{table} tablosundaki {constraint} foreign key''i ({columns} → {referenced}) için bu kolonlarla başlayan bir index yok.'),
('PG-IDX-004', 'en', 'NAME', 'Foreign key without index'),
('PG-IDX-004', 'en', 'HEALTHY', 'Every foreign key on a large table has an index starting with its columns.'),
('PG-IDX-004', 'en', 'MEANING', 'Some large tables have no index starting with their foreign key columns.'),
('PG-IDX-004', 'en', 'CAUSES', E'- PostgreSQL does not create an index on the referencing side of a foreign key; it has to be added by hand\n- It caused no trouble while the table was small and shows as it grows'),
('PG-IDX-004', 'en', 'IMPACT', 'Deleting a referenced row or changing its key makes PostgreSQL scan this whole table; the operation is slow and the locks it holds meanwhile can make other work wait. Joins on these columns are slow too.'),
('PG-IDX-004', 'en', 'RECOMMENDATION', E'- Add an index on the foreign key columns with CREATE INDEX CONCURRENTLY\n- List the columns in the order of the foreign key; extending an existing index at its start can also be enough'),
('PG-IDX-004', 'en', 'FINDING', 'Foreign key {constraint} on {table} ({columns} → {referenced}) has no index starting with its columns.'),
-- PG-BKP-003 ----------------------------------------------------------------
('PG-BKP-003', 'tr', 'NAME', 'Unlogged tablo'),
('PG-BKP-003', 'tr', 'HEALTHY', 'Unlogged tablo yok.'),
('PG-BKP-003', 'tr', 'MEANING', 'Bazı tablolar unlogged: değişiklikleri WAL''e yazılmıyor.'),
('PG-BKP-003', 'tr', 'CAUSES', E'- Önbellek ya da geçici veri için bilinçli olarak hız tercih edildi\n- Toplu veri yüklemesi için unlogged yapıldı ve sonra geri çevrilmedi'),
('PG-BKP-003', 'tr', 'IMPACT', 'Unlogged tabloların içeriği bir çökme sonrasında silinir, replica''lara aktarılmaz (failover''dan sonra tablo boştur) ve WAL tabanlı yedeklerde yer almaz. Bilinçli bir tercihse sorun değildir.'),
('PG-BKP-003', 'tr', 'RECOMMENDATION', E'- Tablonun içeriğinin kaybolmasının kabul edilebilir olduğunu uygulama sahibiyle doğrulayın\n- Değilse ALTER TABLE ... SET LOGGED çalıştırın; tablo yeniden yazılır, büyük tablolarda bakım penceresi planlayın'),
('PG-BKP-003', 'tr', 'FINDING', '{table} tablosu unlogged ({size_bytes}).'),
('PG-BKP-003', 'en', 'NAME', 'Unlogged tables'),
('PG-BKP-003', 'en', 'HEALTHY', 'There are no unlogged tables.'),
('PG-BKP-003', 'en', 'MEANING', 'Some tables are unlogged: their changes are not written to the WAL.'),
('PG-BKP-003', 'en', 'CAUSES', E'- Speed was chosen deliberately for a cache or temporary data\n- The table was made unlogged for a bulk load and not switched back'),
('PG-BKP-003', 'en', 'IMPACT', 'The contents of unlogged tables are emptied after a crash, are not sent to replicas (the table is empty after a failover) and are not in WAL-based backups. If this is a deliberate choice it is not a problem.'),
('PG-BKP-003', 'en', 'RECOMMENDATION', E'- Confirm with the application owner that losing the table''s contents is acceptable\n- If not, run ALTER TABLE ... SET LOGGED; the table is rewritten, plan a maintenance window for large tables'),
('PG-BKP-003', 'en', 'FINDING', 'Table {table} is unlogged ({size_bytes}).'),
-- PG-LIFE-004 ---------------------------------------------------------------
('PG-LIFE-004', 'tr', 'NAME', 'Güncellenebilir extension'),
('PG-LIFE-004', 'tr', 'HEALTHY', 'Bütün extension''lar sunucudaki paketin sürümünde.'),
('PG-LIFE-004', 'tr', 'MEANING', 'Bazı extension''ların veritabanında kurulu sürümü, sunucuda yüklü paketin sürümünden farklı.'),
('PG-LIFE-004', 'tr', 'CAUSES', E'- Extension paketi güncellendi ama veritabanında ALTER EXTENSION ... UPDATE çalıştırılmadı\n- PostgreSQL yükseltmesinden sonra extension''lar güncellenmedi'),
('PG-LIFE-004', 'tr', 'IMPACT', 'Paketle gelen hata ve güvenlik düzeltmeleri veritabanındaki extension''a uygulanmamış olabilir; bazı extension''larda eski sürüm ile yeni kütüphane birlikte beklenmedik davranabilir.'),
('PG-LIFE-004', 'tr', 'RECOMMENDATION', E'- Extension''ın sürüm notlarını okuyun\n- Bakım penceresinde ilgili veritabanında ALTER EXTENSION <ad> UPDATE çalıştırın'),
('PG-LIFE-004', 'tr', 'FINDING', '{database_name} veritabanındaki {extension} extension''ı {installed} sürümünde; sunucudaki paket {available}.'),
('PG-LIFE-004', 'en', 'NAME', 'Extension update available'),
('PG-LIFE-004', 'en', 'HEALTHY', 'Every extension is at the version of the package on the server.'),
('PG-LIFE-004', 'en', 'MEANING', 'Some extensions are installed in a database at a version different from the package on the server.'),
('PG-LIFE-004', 'en', 'CAUSES', E'- The extension package was updated but ALTER EXTENSION ... UPDATE was not run in the database\n- Extensions were not updated after a PostgreSQL upgrade'),
('PG-LIFE-004', 'en', 'IMPACT', 'Bug and security fixes of the package may not apply to the extension in the database; with some extensions the old version and the new library together can behave unexpectedly.'),
('PG-LIFE-004', 'en', 'RECOMMENDATION', E'- Read the extension''s release notes\n- Run ALTER EXTENSION <name> UPDATE in the database in a maintenance window'),
('PG-LIFE-004', 'en', 'FINDING', 'Extension {extension} in database {database_name} is at version {installed}; the server has {available}.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
