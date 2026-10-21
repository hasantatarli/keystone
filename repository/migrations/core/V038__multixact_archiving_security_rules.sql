/*
===============================================================================
Migration No : 038
Version      : V038
Title        : MultiXact, WAL Archiving and Security Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-TRAN-004 MultiXact Wraparound Risk, PG-BKP-002 WAL Archiving
(PG_BACKUP_HEALTH, topic BACKUP), PG-SEC-002 MD5 Password Encryption and
PG-SEC-003 SSL Disabled (PG_SECURITY_HEALTH, topic SECURITY).
===============================================================================
*/


/*
Design notes (2026-10-21, PostgreSQL V1 Assessment Catalogue, P1)
-----------------------------------------------------------------
- PG-TRAN-004 mirrors PG-TRAN-002 on mxid_age (1.5 / 1.8 billion). MultiXact
  member space exhaustion is not visible in this evidence.
- PG-BKP-002 judges the primary only: archive_mode off is WARNING (no
  point-in-time recovery; may be a conscious choice), archive_mode on with an
  empty archive_command and archive_library is CRITICAL (WAL files accumulate
  until the disk is full).
- PG-SEC-002 / PG-SEC-003 judge every node's server-level setting. Roles that
  still have md5 password hashes need pg_authid (superuser) and are not seen.
===============================================================================
*/


/* ============================================================================
   TOPICS AND ASSESSMENTS
   ============================================================================ */

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('BACKUP',   70),
    ('SECURITY', 80)
ON CONFLICT (topic_key) DO NOTHING;

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name) VALUES
    ('BACKUP',   'tr', 'Yedekleme ve kurtarma'),
    ('BACKUP',   'en', 'Backup and recovery'),
    ('SECURITY', 'tr', 'Güvenlik'),
    ('SECURITY', 'en', 'Security')
ON CONFLICT (topic_key, language_code) DO NOTHING;

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_BACKUP_HEALTH', 'Backup Health', 'PostgreSQL',
     'Evaluates whether the PostgreSQL system can be recovered: WAL archiving and backups.', 3600),
    ('PG_SECURITY_HEALTH', 'Security Health', 'PostgreSQL',
     'Evaluates PostgreSQL authentication and connection security settings.', 3600)
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
    ('PG_TRANSACTION_HEALTH', 'PG-TRAN-004', 'Database MultiXact Wraparound Risk',
     'Detects databases whose MultiXact ID age approaches the wraparound limit.',
     'PG_TRANSACTION_WRAPAROUND', NULL,
     'Database {database_name} has a MultiXact ID age of {mxid_age}.',
     'Check that autovacuum keeps up in this database, find the tables with the oldest relminmxid and run a planned VACUUM (FREEZE).',
     'MAINTENANCE'),
    ('PG_BACKUP_HEALTH', 'PG-BKP-002', 'WAL Archiving',
     'Detects a primary without WAL archiving, or with archiving enabled but no archive command.',
     'PG_CONFIGURATION_SNAPSHOT', NULL,
     'Setting {setting} is {value} on {node_name}.',
     'Decide whether point-in-time recovery is needed; if so, configure WAL archiving with a backup tool. If archive_mode is on, set archive_command or archive_library.',
     'BACKUP'),
    ('PG_SECURITY_HEALTH', 'PG-SEC-002', 'MD5 Password Encryption',
     'Detects servers that store new passwords as md5 hashes instead of SCRAM-SHA-256.',
     'PG_CONFIGURATION_SNAPSHOT', 'WARNING',
     'Setting {setting} is {value} on {node_name}.',
     'Set password_encryption to scram-sha-256, then reset the passwords of roles that still have md5 hashes and switch pg_hba.conf rules to scram-sha-256.',
     'SECURITY'),
    ('PG_SECURITY_HEALTH', 'PG-SEC-003', 'SSL Disabled',
     'Detects servers that do not accept encrypted connections.',
     'PG_CONFIGURATION_SNAPSHOT', 'WARNING',
     'Setting {setting} is {value} on {node_name}.',
     'Enable ssl with a certificate and require it for remote connections in pg_hba.conf (hostssl).',
     'SECURITY')
) AS r (assessment_key, rule_key, name, description, evidence_source, default_severity,
        finding_template, recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = r.assessment_key
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   THRESHOLDS AND EVIDENCE
   ============================================================================ */

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, t.threshold_unit
FROM keystone.rule_definition rd
CROSS JOIN (VALUES
    ('WARNING',  1500000000, 'MULTIXACT'),
    ('CRITICAL', 1800000000, 'MULTIXACT')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-TRAN-004'
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, TRUE, r.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-004', 'PG_TRANSACTION_WRAPAROUND', 86400),
    ('PG-BKP-002',  'PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG-BKP-002',  'PG_INSTANCE_INVENTORY',     3600),
    ('PG-SEC-002',  'PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG-SEC-003',  'PG_CONFIGURATION_SNAPSHOT', 86400)
) AS r (rule_key, evidence_source, max_age_seconds) ON r.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;


/* ============================================================================
   IMPACT CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-004', 'AVAILABILITY'),
    ('PG-BKP-002',  'DATA_SAFETY'),
    ('PG-SEC-002',  'SECURITY'),
    ('PG-SEC-003',  'SECURITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-TRAN-004 ---------------------------------------------------------------
('PG-TRAN-004', 'tr', 'NAME', 'MultiXact ID wraparound riski'),
('PG-TRAN-004', 'tr', 'HEALTHY', 'Hiçbir veritabanında MultiXact ID yaşı {warning} sınırına ulaşmamış.'),
('PG-TRAN-004', 'tr', 'MEANING', 'Birden fazla transaction''ın aynı satırı kilitlediği durumlar için kullanılan MultiXact ID sayacı, transaction ID gibi başa dönme sınırına yaklaşıyor.'),
('PG-TRAN-004', 'tr', 'CAUSES', E'- Autovacuum yetişemiyor ya da kapatılmış\n- Foreign key''ler ya da SELECT ... FOR SHARE yüzünden yoğun satır kilitleme\n- Vacuum''u engelleyen uzun transaction''lar'),
('PG-TRAN-004', 'tr', 'IMPACT', 'Sınıra ulaşılırsa PostgreSQL, veri bozulmasını önlemek için yeni yazma işlemlerini kabul etmez ve uygulamalar veritabanına yazamaz hale gelir.'),
('PG-TRAN-004', 'tr', 'RECOMMENDATION', E'- Autovacuum''un bu veritabanında çalıştığını doğrulayın\n- MultiXact yaşı en yüksek tabloları belirleyin (mxid_age(relminmxid))\n- Planlı bir VACUUM (FREEZE) çalıştırın'),
('PG-TRAN-004', 'en', 'NAME', 'MultiXact ID wraparound risk'),
('PG-TRAN-004', 'en', 'HEALTHY', 'No database has reached a MultiXact ID age of {warning}.'),
('PG-TRAN-004', 'en', 'MEANING', 'The MultiXact ID counter, used when several transactions lock the same row, is approaching its wraparound limit, like the transaction ID counter.'),
('PG-TRAN-004', 'en', 'CAUSES', E'- Autovacuum is not keeping up or is disabled\n- Heavy row locking from foreign keys or SELECT ... FOR SHARE\n- Long transactions blocking vacuum'),
('PG-TRAN-004', 'en', 'IMPACT', 'If the limit is reached, PostgreSQL stops accepting new writes to prevent data corruption and applications can no longer write to the database.'),
('PG-TRAN-004', 'en', 'RECOMMENDATION', E'- Verify that autovacuum runs in this database\n- Find the tables with the highest MultiXact age (mxid_age(relminmxid))\n- Run a planned VACUUM (FREEZE)'),

-- PG-BKP-002 ----------------------------------------------------------------
('PG-BKP-002', 'tr', 'NAME', 'WAL arşivleme'),
('PG-BKP-002', 'tr', 'HEALTHY', 'Primary''de WAL arşivleme açık ve bir arşivleme komutu tanımlı.'),
('PG-BKP-002', 'tr', 'MEANING', 'Primary''de WAL arşivleme kapalı ya da açık olduğu halde arşivleme komutu tanımlı değil.'),
('PG-BKP-002', 'tr', 'CAUSES', E'- Yedekleme yalnızca pg_dump ya da disk snapshot''ı ile yapılıyor\n- Arşivleme hiç yapılandırılmamış\n- Arşivleme komutu kaldırılmış ya da yedekleme aracı değiştirilmiş'),
('PG-BKP-002', 'tr', 'IMPACT', 'Arşivleme kapalıysa veritabanı yalnızca son tam yedeğin alındığı ana döndürülebilir; arada yapılan değişiklikler kaybolur (point-in-time recovery yok). Arşivleme açık ama komut boşsa, WAL dosyaları hiç silinmez ve disk dolar.'),
('PG-BKP-002', 'tr', 'RECOMMENDATION', E'- Bu sistem için point-in-time recovery gerekip gerekmediğine karar verin\n- Gerekiyorsa pgBackRest, Barman ya da WAL-G gibi bir araçla WAL arşivlemeyi yapılandırın\n- archive_mode açıksa archive_command ya da archive_library tanımlayın'),
('PG-BKP-002', 'en', 'NAME', 'WAL archiving'),
('PG-BKP-002', 'en', 'HEALTHY', 'WAL archiving is on for the primary and an archive command is set.'),
('PG-BKP-002', 'en', 'MEANING', 'WAL archiving is off on the primary, or it is on without an archive command.'),
('PG-BKP-002', 'en', 'CAUSES', E'- Backups are taken only with pg_dump or disk snapshots\n- Archiving was never configured\n- The archive command was removed or the backup tool changed'),
('PG-BKP-002', 'en', 'IMPACT', 'With archiving off, the database can only be restored to the time of the last full backup; changes made since are lost (no point-in-time recovery). With archiving on and no command, WAL files are never removed and the disk fills up.'),
('PG-BKP-002', 'en', 'RECOMMENDATION', E'- Decide whether this system needs point-in-time recovery\n- If so, configure WAL archiving with a tool such as pgBackRest, Barman or WAL-G\n- If archive_mode is on, set archive_command or archive_library'),

-- PG-SEC-002 ----------------------------------------------------------------
('PG-SEC-002', 'tr', 'NAME', 'MD5 ile şifre saklama'),
('PG-SEC-002', 'tr', 'HEALTHY', 'Yeni şifreler SCRAM-SHA-256 ile saklanıyor; password_encryption md5 değil.'),
('PG-SEC-002', 'tr', 'MEANING', 'Sunucu yeni ya da değiştirilen şifreleri eski ve zayıf md5 yöntemiyle saklıyor.'),
('PG-SEC-002', 'tr', 'CAUSES', E'- Eski bir PostgreSQL sürümünden yükseltmede ayar korunmuş\n- md5 destekleyen eski bir istemci sürücüsü için bilerek bırakılmış'),
('PG-SEC-002', 'tr', 'IMPACT', 'md5 hash''leri ele geçirilirse şifrenin kendisi bilinmeden de oturum açmak için kullanılabilir. md5 PostgreSQL 18''de kullanımdan kaldırılma sürecinde.'),
('PG-SEC-002', 'tr', 'RECOMMENDATION', E'- password_encryption ayarını scram-sha-256 yapın\n- md5 hash''i kalan rollerin şifrelerini yeniden belirleyin\n- pg_hba.conf''taki md5 kurallarını scram-sha-256 yapın\n- Önce istemci sürücülerinin SCRAM desteklediğini doğrulayın'),
('PG-SEC-002', 'en', 'NAME', 'MD5 password encryption'),
('PG-SEC-002', 'en', 'HEALTHY', 'New passwords are stored with SCRAM-SHA-256; password_encryption is not md5.'),
('PG-SEC-002', 'en', 'MEANING', 'The server stores new or changed passwords with the old and weak md5 method.'),
('PG-SEC-002', 'en', 'CAUSES', E'- The setting was kept when upgrading from an old PostgreSQL version\n- It was left on purpose for an old client driver that supports only md5'),
('PG-SEC-002', 'en', 'IMPACT', 'A stolen md5 hash can be used to log in without knowing the password itself. md5 is being deprecated in PostgreSQL 18.'),
('PG-SEC-002', 'en', 'RECOMMENDATION', E'- Set password_encryption to scram-sha-256\n- Reset the passwords of roles that still have md5 hashes\n- Change md5 rules in pg_hba.conf to scram-sha-256\n- Verify first that client drivers support SCRAM'),

-- PG-SEC-003 ----------------------------------------------------------------
('PG-SEC-003', 'tr', 'NAME', 'SSL kapalı'),
('PG-SEC-003', 'tr', 'HEALTHY', 'Sunucular SSL ile şifreli bağlantı kabul ediyor.'),
('PG-SEC-003', 'tr', 'MEANING', 'Sunucu şifreli (SSL) bağlantı kabul etmiyor; tüm bağlantılar ağda açık metin olarak taşınıyor.'),
('PG-SEC-003', 'tr', 'CAUSES', E'- Sertifika hiç yapılandırılmamış\n- Veritabanının yalnızca güvenli bir iç ağdan erişildiği varsayılmış'),
('PG-SEC-003', 'tr', 'IMPACT', 'Ağı dinleyebilen biri sorguları, sonuçları ve oturum bilgilerini görebilir; bağlantı araya girilerek değiştirilebilir.'),
('PG-SEC-003', 'tr', 'RECOMMENDATION', E'- Bir sertifikayla ssl ayarını açın\n- Uzak bağlantılar için pg_hba.conf''ta hostssl kullanarak şifrelemeyi zorunlu kılın\n- İstemcilerde sslmode=verify-full kullanın'),
('PG-SEC-003', 'en', 'NAME', 'SSL disabled'),
('PG-SEC-003', 'en', 'HEALTHY', 'The servers accept encrypted (SSL) connections.'),
('PG-SEC-003', 'en', 'MEANING', 'The server does not accept encrypted (SSL) connections; all connections travel as plain text on the network.'),
('PG-SEC-003', 'en', 'CAUSES', E'- No certificate was ever configured\n- The database was assumed to be reachable only from a trusted internal network'),
('PG-SEC-003', 'en', 'IMPACT', 'Anyone who can listen on the network can see queries, results and session details; the connection can be intercepted and altered.'),
('PG-SEC-003', 'en', 'RECOMMENDATION', E'- Enable ssl with a certificate\n- Require encryption for remote connections with hostssl in pg_hba.conf\n- Use sslmode=verify-full on clients')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
