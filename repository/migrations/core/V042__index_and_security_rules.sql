/*
===============================================================================
Migration No : 042
Version      : V042
Title        : Index and Security Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds collector scope NODE_DATABASE, PG_INDEX_HEALTH (topic INDEXES) with
PG-IDX-001 Unused Index and PG-IDX-002 Invalid Index, and PG-SEC-001 Login
Superuser and PG-SEC-004 PUBLIC Can Create in Schema (PG_SECURITY_HEALTH).
===============================================================================
*/


/*
Design notes (2026-10-26/27, Hasan)
-----------------------------------
- NODE_DATABASE: run in every database of every node. Index scan counts are
  kept per server; an index unused on the primary may serve reports on a
  replica, and dropping it on the primary drops it everywhere.
- PG-IDX-001: an index is unused only if its scans summed over all nodes are
  0. A sum above 0 on the reachable nodes is enough to call it used; a sum of
  0 with a node not collected cannot be decided (INSUFFICIENT_EVIDENCE). The
  statistics age is the shortest over the nodes and is always stated; under
  min_statistics_age nothing is judged, under full_cycle the finding warns
  about periodic use (an index used only at year end was dropped in the field
  and the year-end bank transfer failed). WARNING, never CRITICAL. Indexes
  backing primary key, unique or exclusion constraints are not judged.
- PG-IDX-002: invalid indexes on the primary; an index still being built
  concurrently is not reported. Unique invalid index is CRITICAL (uniqueness
  is not enforced), others WARNING.
- PG-SEC-001: every login superuser except the bootstrap superuser (OID 10).
- PG-SEC-004: CREATE on a user schema granted to PUBLIC (default for public
  before PostgreSQL 15, kept by upgrades). template1 is not collected.
===============================================================================
*/

ALTER TABLE keystone.collector_definition
    DROP CONSTRAINT ck_collector_definition_execution_scope;

ALTER TABLE keystone.collector_definition
    ADD CONSTRAINT ck_collector_definition_execution_scope
    CHECK (execution_scope IN ('SYSTEM', 'NODE', 'DATABASE', 'NODE_DATABASE'));


/* ============================================================================
   TOPIC AND ASSESSMENT
   ============================================================================ */

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('INDEXES', 25)
ON CONFLICT (topic_key) DO NOTHING;

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name) VALUES
    ('INDEXES', 'tr', 'Index''ler'),
    ('INDEXES', 'en', 'Indexes')
ON CONFLICT (topic_key, language_code) DO NOTHING;

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_INDEX_HEALTH', 'Index Health', 'PostgreSQL',
     'Evaluates whether indexes are used and valid, across all servers of the system.', 86400)
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
    ('PG_INDEX_HEALTH', 'PG-IDX-001', 'Unused Index',
     'Detects indexes not scanned on any server since their statistics began.',
     'PG_INDEX_USAGE', 'WARNING',
     'Index {index} on {table} was not used on any server ({nodes}; statistics cover {statistics_seconds} seconds). Size: {index_size} bytes.',
     'Do not drop it before checking periodic use (month, quarter or year end) with the application team; keep watching its scan count.',
     'INDEXES'),
    ('PG_INDEX_HEALTH', 'PG-IDX-002', 'Invalid Index',
     'Detects invalid indexes left by a failed CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY.',
     'PG_INDEX_USAGE', 'WARNING',
     'Index {index} on {table} is invalid.',
     'Rebuild it with REINDEX INDEX CONCURRENTLY, or drop it with DROP INDEX CONCURRENTLY and create it again; for a unique index check for duplicates first.',
     'INDEXES'),
    ('PG_SECURITY_HEALTH', 'PG-SEC-001', 'Login Superuser',
     'Detects login roles with superuser besides the bootstrap superuser.',
     'PG_ROLES', 'WARNING',
     'Role {role} is a superuser that can log in.',
     'Check whether the role needs superuser; give applications only the privileges they use and use predefined roles such as pg_monitor for administration.',
     'SECURITY'),
    ('PG_SECURITY_HEALTH', 'PG-SEC-004', 'PUBLIC Can Create in Schema',
     'Detects user schemas in which every role (PUBLIC) may create objects.',
     'PG_SCHEMA_PRIVILEGES', 'WARNING',
     'Every role (PUBLIC) can create objects in schema {schema} of database {database}.',
     'Revoke CREATE on the schema from PUBLIC after granting it to the roles that deploy objects there.',
     'SECURITY')
) AS r (assessment_key, rule_key, name, description, evidence_source, default_severity,
        finding_template, recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = r.assessment_key
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   PARAMETERS, EVIDENCE, CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rd.rule_id, p.parameter_key, p.parameter_value, p.parameter_unit, p.description
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-001', 'min_index_size',     10485760, 'BYTE',
     'Smaller indexes are not judged.'),
    ('PG-IDX-001', 'min_statistics_age', 604800,   'SECOND',
     'Younger statistics are not judged.'),
    ('PG-IDX-001', 'full_cycle',         31536000, 'SECOND',
     'Statistics younger than this may miss periodic use; the finding says so.')
) AS p (rule_key, parameter_key, parameter_value, parameter_unit, description) ON p.rule_key = rd.rule_key
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, TRUE, 86400
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-001', 'PG_INDEX_USAGE'),
    ('PG-IDX-002', 'PG_INDEX_USAGE'),
    ('PG-SEC-001', 'PG_ROLES'),
    ('PG-SEC-004', 'PG_SCHEMA_PRIVILEGES')
) AS r (rule_key, evidence_source) ON r.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-001', 'PERFORMANCE'),
    ('PG-IDX-001', 'CAPACITY'),
    ('PG-IDX-002', 'PERFORMANCE'),
    ('PG-IDX-002', 'DATA_SAFETY'),
    ('PG-SEC-001', 'SECURITY'),
    ('PG-SEC-004', 'SECURITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-IDX-001 ----------------------------------------------------------------
('PG-IDX-001', 'tr', 'NAME', 'Kullanılmayan index'),
('PG-IDX-001', 'tr', 'HEALTHY', 'Bütün sunucularda hiç kullanılmamış büyük index yok.'),
('PG-IDX-001', 'tr', 'MEANING', 'Bazı index''ler istatistiklerin tutulduğu süre boyunca hiçbir sunucuda hiçbir sorguda kullanılmamış.'),
('PG-IDX-001', 'tr', 'CAUSES', E'- Index''i kullanan sorgu ya da uygulama özelliği kaldırıldı\n- Aynı işi gören başka bir index eklendi\n- Index yalnızca dönemsel işlerde (ay, çeyrek ya da yıl sonu) kullanılıyor ve istatistik süresi o dönemi kapsamıyor\n- Index tahminle oluşturuldu ama planner hiç seçmedi'),
('PG-IDX-001', 'tr', 'IMPACT', 'Kullanılmayan index her INSERT, UPDATE ve DELETE''te yine güncellenir: yazmalar yavaşlar, disk, vacuum ve backup süresi boşuna artar. Yanlışlıkla dönemsel bir index silinirse o iş çok yavaşlar ya da zaman aşımına uğrar.'),
('PG-IDX-001', 'tr', 'RECOMMENDATION', E'- Silmeden önce uygulama ekibine index''in ay, çeyrek ya da yıl sonu gibi dönemsel işlerde kullanılıp kullanılmadığını sorun\n- İstatistikler bir yıldan kısaysa index kullanımını en az bir tam iş dönemi boyunca izlemeye devam edin\n- Kullanılmadığı kesinleşen index''i yoğun olmayan bir saatte DROP INDEX CONCURRENTLY ile kaldırın ve tanımını saklayın'),
('PG-IDX-001', 'tr', 'FINDING', '{index} index''i ({table}) hiçbir sunucuda kullanılmamış ({nodes}; istatistik süresi: {statistics_seconds}). Boyut: {index_size}.'),
('PG-IDX-001', 'tr', 'FINDING_ALT', '{index} index''i ({table}) hiçbir sunucuda kullanılmamış ({nodes}; istatistik süresi: {statistics_seconds}). Boyut: {index_size}. İstatistikler bir yıldan kısa; yıl sonu, çeyrek kapanışı gibi dönemsel işlerde kullanılan index''ler bu sürede görünmeyebilir.'),
('PG-IDX-001', 'en', 'NAME', 'Unused index'),
('PG-IDX-001', 'en', 'HEALTHY', 'No large index went unused on all servers.'),
('PG-IDX-001', 'en', 'MEANING', 'Some indexes were not used by any query on any server while their statistics were kept.'),
('PG-IDX-001', 'en', 'CAUSES', E'- The query or application feature that used the index was removed\n- Another index doing the same job was added\n- The index is used only by periodic jobs (month, quarter or year end) and the statistics do not cover that period\n- The index was created on a guess and the planner never chose it'),
('PG-IDX-001', 'en', 'IMPACT', 'An unused index is still updated by every INSERT, UPDATE and DELETE: writes slow down, and disk, vacuum and backup time grow for nothing. Dropping a periodically used index by mistake makes that job very slow or time out.'),
('PG-IDX-001', 'en', 'RECOMMENDATION', E'- Before dropping it, ask the application team whether periodic jobs (month, quarter or year end) use the index\n- If the statistics cover less than a year, keep watching its use for at least one full business cycle\n- Drop an index confirmed as unused with DROP INDEX CONCURRENTLY at a quiet time and keep its definition'),
('PG-IDX-001', 'en', 'FINDING', 'Index {index} ({table}) was not used on any server ({nodes}; statistics cover {statistics_seconds}). Size: {index_size}.'),
('PG-IDX-001', 'en', 'FINDING_ALT', 'Index {index} ({table}) was not used on any server ({nodes}; statistics cover {statistics_seconds}). Size: {index_size}. The statistics cover less than a year; indexes used by periodic jobs such as year or quarter end may not show up in that time.'),

-- PG-IDX-002 ----------------------------------------------------------------
('PG-IDX-002', 'tr', 'NAME', 'Geçersiz index'),
('PG-IDX-002', 'tr', 'HEALTHY', 'Geçersiz (invalid) index yok.'),
('PG-IDX-002', 'tr', 'MEANING', 'Yarıda kalmış bir CREATE INDEX CONCURRENTLY ya da REINDEX CONCURRENTLY geride geçersiz bir index bırakmış.'),
('PG-IDX-002', 'tr', 'CAUSES', E'- CREATE INDEX CONCURRENTLY hata aldı, iptal edildi ya da bağlantısı koptu\n- Unique index oluşturulurken tekrarlı kayıt bulundu\n- REINDEX CONCURRENTLY yarıda kaldı'),
('PG-IDX-002', 'tr', 'IMPACT', 'Geçersiz index hiçbir sorguda kullanılmaz ama her yazmada güncellenmeye devam eder. Unique ise tekillik kontrolü yapılmaz: ekip kısıt olduğunu sanar, ama tekrarlı kayıt girebilir.'),
('PG-IDX-002', 'tr', 'RECOMMENDATION', E'- Index''i REINDEX INDEX CONCURRENTLY ile yeniden oluşturun\n- Ya da DROP INDEX CONCURRENTLY ile silip yeniden oluşturun\n- Unique index ise önce tekrarlı kayıtları bulup temizleyin, yoksa yeniden oluşturma da başarısız olur'),
('PG-IDX-002', 'tr', 'FINDING', '{index} index''i ({table}) geçersiz; hiçbir sorguda kullanılmıyor ama her yazmada güncelleniyor.'),
('PG-IDX-002', 'tr', 'FINDING_ALT', '{index} unique index''i ({table}) geçersiz; tekillik kontrolü yapılmıyor, tekrarlı kayıt girebilir.'),
('PG-IDX-002', 'en', 'NAME', 'Invalid index'),
('PG-IDX-002', 'en', 'HEALTHY', 'There is no invalid index.'),
('PG-IDX-002', 'en', 'MEANING', 'An interrupted CREATE INDEX CONCURRENTLY or REINDEX CONCURRENTLY left an invalid index behind.'),
('PG-IDX-002', 'en', 'CAUSES', E'- CREATE INDEX CONCURRENTLY failed, was cancelled or lost its connection\n- Duplicates were found while building a unique index\n- REINDEX CONCURRENTLY was interrupted'),
('PG-IDX-002', 'en', 'IMPACT', 'An invalid index is never used by queries but is still updated by every write. If it is unique, uniqueness is not enforced: the team believes the constraint exists, but duplicates can be inserted.'),
('PG-IDX-002', 'en', 'RECOMMENDATION', E'- Rebuild the index with REINDEX INDEX CONCURRENTLY\n- Or drop it with DROP INDEX CONCURRENTLY and create it again\n- For a unique index, find and remove duplicates first, or the rebuild fails too'),
('PG-IDX-002', 'en', 'FINDING', 'Index {index} ({table}) is invalid; no query uses it but every write still updates it.'),
('PG-IDX-002', 'en', 'FINDING_ALT', 'Unique index {index} ({table}) is invalid; uniqueness is not enforced and duplicates can be inserted.'),

-- PG-SEC-001 ----------------------------------------------------------------
('PG-SEC-001', 'tr', 'NAME', 'Login yapabilen superuser'),
('PG-SEC-001', 'tr', 'HEALTHY', 'Bootstrap superuser dışında login yapabilen superuser yok.'),
('PG-SEC-001', 'tr', 'MEANING', 'Kurulumda oluşan superuser dışında, login yapabilen başka superuser rolleri var.'),
('PG-SEC-001', 'tr', 'CAUSES', E'- Uygulama kullanıcısı yetki hatası alınca superuser yapıldı\n- ETL, migration ya da izleme araçlarına kolaylık olsun diye superuser verildi\n- Kişisel yönetici hesapları superuser olarak açıldı'),
('PG-SEC-001', 'tr', 'IMPACT', 'Superuser bütün yetki kontrollerini atlar: her veriyi okuyup silebilir, sunucuda işletim sistemi komutu çalıştırabilir (COPY ... PROGRAM). Bu rolü kullanan bir uygulamadaki SQL injection, sunucunun tamamen ele geçirilmesi demektir.'),
('PG-SEC-001', 'tr', 'RECOMMENDATION', E'- Her superuser rolünün gerçekten gerekli olup olmadığını gözden geçirin\n- Uygulama ve ETL kullanıcılarından superuser''ı alıp yalnızca ihtiyaç duydukları yetkileri verin\n- Yönetim işleri için pg_monitor, pg_signal_backend gibi hazır rolleri kullanın\n- Kalması gereken yönetici hesaplarını kişiye özel açın ve kullanımlarını loglayın'),
('PG-SEC-001', 'tr', 'FINDING', '{role} rolü login yapabilen bir superuser.'),
('PG-SEC-001', 'en', 'NAME', 'Login superuser'),
('PG-SEC-001', 'en', 'HEALTHY', 'No login superuser besides the bootstrap superuser.'),
('PG-SEC-001', 'en', 'MEANING', 'Besides the superuser created at installation, other roles that can log in are superusers.'),
('PG-SEC-001', 'en', 'CAUSES', E'- An application user was made superuser after a permission error\n- ETL, migration or monitoring tools were given superuser for convenience\n- Personal administrator accounts were created as superusers'),
('PG-SEC-001', 'en', 'IMPACT', 'A superuser bypasses every permission check: it can read and delete all data and run operating system commands on the server (COPY ... PROGRAM). SQL injection in an application using such a role means the whole server is taken over.'),
('PG-SEC-001', 'en', 'RECOMMENDATION', E'- Review whether each superuser role really needs it\n- Remove superuser from application and ETL users and grant only the privileges they use\n- Use predefined roles such as pg_monitor and pg_signal_backend for administration\n- Keep remaining administrator accounts personal and log their use'),
('PG-SEC-001', 'en', 'FINDING', 'Role {role} is a superuser that can log in.'),

-- PG-SEC-004 ----------------------------------------------------------------
('PG-SEC-004', 'tr', 'NAME', 'Herkesin nesne oluşturabildiği schema'),
('PG-SEC-004', 'tr', 'HEALTHY', 'Hiçbir kullanıcı schema''sında herkese (PUBLIC) nesne oluşturma yetkisi verilmemiş.'),
('PG-SEC-004', 'tr', 'MEANING', 'Bazı schema''larda veritabanına bağlanabilen her kullanıcı (PUBLIC) tablo, fonksiyon ya da operatör oluşturabiliyor.'),
('PG-SEC-004', 'tr', 'CAUSES', E'- Veritabanı PostgreSQL 15 öncesinde oluşturuldu; public schema''da herkese CREATE yetkisi o zaman varsayılandı ve upgrade ile korundu\n- Yetki bilerek ya da kolaylık için herkese verildi'),
('PG-SEC-004', 'tr', 'IMPACT', 'Herhangi bir kullanıcı, sistem fonksiyonlarıyla aynı adı taşıyan bir nesne koyarak search_path üzerinden başka kullanıcıların, superuser dahil, sorgularında kendi kodunu çalıştırabilir (CVE-2018-1058). Herkes tablo oluşturup diski de doldurabilir.'),
('PG-SEC-004', 'tr', 'RECOMMENDATION', E'- Bu schema''da nesne oluşturan uygulama ve deploy kullanıcılarına CREATE yetkisini ayrıca verin\n- Ardından REVOKE CREATE ON SCHEMA <schema> FROM PUBLIC çalıştırın\n- Uygulama kullanıcılarının search_path ayarında güvenilmeyen schema''ları önce yazmayın'),
('PG-SEC-004', 'tr', 'FINDING', '{database} veritabanında {schema} schema''sında herkes (PUBLIC) nesne oluşturabiliyor.'),
('PG-SEC-004', 'en', 'NAME', 'PUBLIC can create in schema'),
('PG-SEC-004', 'en', 'HEALTHY', 'No user schema lets every role (PUBLIC) create objects.'),
('PG-SEC-004', 'en', 'MEANING', 'In some schemas every role that can connect (PUBLIC) can create tables, functions or operators.'),
('PG-SEC-004', 'en', 'CAUSES', E'- The database was created before PostgreSQL 15, when CREATE on schema public for everyone was the default, and upgrades kept it\n- The privilege was granted to everyone on purpose or for convenience'),
('PG-SEC-004', 'en', 'IMPACT', 'Any user can place an object named like a system function and, through search_path, run their own code in other users'' queries, superusers included (CVE-2018-1058). Anyone can also create tables and fill the disk.'),
('PG-SEC-004', 'en', 'RECOMMENDATION', E'- Grant CREATE on the schema to the application and deploy users that create objects there\n- Then run REVOKE CREATE ON SCHEMA <schema> FROM PUBLIC\n- Do not put untrusted schemas first in the search_path of application users'),
('PG-SEC-004', 'en', 'FINDING', 'Every role (PUBLIC) can create objects in schema {schema} of database {database}.')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
