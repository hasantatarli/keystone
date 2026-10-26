/*
===============================================================================
Migration No : 041
Version      : V041
Title        : WAL Archive Failure, Prepared Transaction and Failover Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-BKP-001 WAL Archive Failures (PG_BACKUP_HEALTH), PG-TRAN-005 Long
Prepared Transaction (PG_TRANSACTION_HEALTH) and PG-HA-001 Recent Failover
(PG_REPLICATION_HEALTH), on the new collectors PG_WAL_STATUS and
PG_PREPARED_TRANSACTIONS (provider migration PG015).
===============================================================================
*/


/*
Design notes (2026-10-26, Hasan)
--------------------------------
- PG-BKP-001 is CRITICAL when the last archive failure is newer than the last
  success: archiving is stuck now. Failures followed by a success are history,
  not a finding. Nodes with archive_mode off are left to PG-BKP-002; a replica
  is judged only with archive_mode = always. "No success for a long time" is
  not judged: a quiet system may not switch WAL files for hours.
- PG-TRAN-005 judges the age of each prepared transaction (5 / 60 minutes). It
  holds locks and blocks vacuum without a session, so PG-TRAN-003 cannot see it.
- PG-HA-001 needs no history: the history file of the primary's current
  timeline is written by its own promotion, so its time is the failover time.
  Older history files are not used; pg_basebackup / pg_rewind copy them with a
  new time (lab 2026-10-26). A failover within recent_failover_window is a
  WARNING; planned and unplanned switches look the same.
===============================================================================
*/


/* ============================================================================
   RULE DEFINITIONS
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source,
       r.default_severity, r.finding_template, r.recommendation, r.topic_key
FROM (VALUES
    ('PG_BACKUP_HEALTH', 'PG-BKP-001', 'WAL Archive Failures',
     'Detects servers whose WAL archiving is failing now: the last failure is newer than the last success.',
     'PG_WAL_STATUS', 'CRITICAL',
     'WAL archiving is failing on {node_name}: last failure at {last_failed_time} ({last_failed_wal}), last success at {last_archived_time}.',
     'Find the archive_command error in the PostgreSQL log, check the archive destination and the backup tool, and watch pg_wal until archiving works again.',
     'BACKUP'),
    ('PG_TRANSACTION_HEALTH', 'PG-TRAN-005', 'Long Prepared Transaction',
     'Detects two-phase commit transactions waiting long for COMMIT PREPARED or ROLLBACK PREPARED.',
     'PG_PREPARED_TRANSACTIONS', NULL,
     'Prepared transaction {gid} in database {database_name} (owner {owner}) has been waiting for {age_seconds} seconds.',
     'Ask the owning transaction manager for the outcome, then run COMMIT PREPARED or ROLLBACK PREPARED. Never roll back without it.',
     'TRANSACTIONS'),
    ('PG_REPLICATION_HEALTH', 'PG-HA-001', 'Recent Failover',
     'Detects a failover or switchover within the recent failover window, from the primary''s current timeline.',
     'PG_WAL_STATUS', 'WARNING',
     '{node_name} became primary at {timeline_started_at} (timeline {timeline_id}), {since_seconds} seconds ago.',
     'If the failover was not planned, find its cause in the logs of the old primary and the HA tool, and check that the old primary rejoined as a replica.',
     'REPLICATION')
) AS r (assessment_key, rule_key, name, description, evidence_source, default_severity,
        finding_template, recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = r.assessment_key
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   THRESHOLDS, PARAMETERS, EVIDENCE, CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, 'SECOND'
FROM keystone.rule_definition rd
CROSS JOIN (VALUES
    ('WARNING',  300),
    ('CRITICAL', 3600)
) AS t (severity, threshold_value)
WHERE rd.rule_key = 'PG-TRAN-005'
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rule_id, 'recent_failover_window', 86400, 'SECOND',
       'A failover or switchover this recent is reported.'
FROM keystone.rule_definition
WHERE rule_key = 'PG-HA-001'
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, TRUE, r.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-BKP-001',  'PG_WAL_STATUS',            900),
    ('PG-TRAN-005', 'PG_PREPARED_TRANSACTIONS', 600),
    ('PG-HA-001',   'PG_WAL_STATUS',            900)
) AS r (rule_key, evidence_source, max_age_seconds) ON r.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-BKP-001',  'DATA_SAFETY'),
    ('PG-BKP-001',  'CAPACITY'),
    ('PG-TRAN-005', 'AVAILABILITY'),
    ('PG-TRAN-005', 'PERFORMANCE'),
    ('PG-HA-001',   'AVAILABILITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-BKP-001 ----------------------------------------------------------------
('PG-BKP-001', 'tr', 'NAME', 'WAL arşivleme hatası'),
('PG-BKP-001', 'tr', 'HEALTHY', 'Arşivlemenin açık olduğu sunucularda son arşivleme denemesi başarılı.'),
('PG-BKP-001', 'tr', 'MEANING', 'WAL dosyaları arşive kopyalanamıyor; arşivleme komutu hata veriyor.'),
('PG-BKP-001', 'tr', 'CAUSES', E'- Arşiv hedefi (disk, NFS, object storage) dolu ya da erişilemiyor\n- Yedekleme aracının (pgBackRest, Barman, WAL-G) ayarı ya da yetkisi bozulmuş\n- archive_command yanlış yazılmış ya da kullandığı komut sunucuda yok\n- Yedek sunucusuna ağ bağlantısı kopmuş'),
('PG-BKP-001', 'tr', 'IMPACT', 'Arşivlenemeyen WAL dosyaları silinemez; pg_wal dizini disk dolana kadar büyür ve disk dolunca PostgreSQL durur. Sorun sürdükçe point-in-time recovery mümkün olmaz; son yedekten sonraki değişiklikler geri getirilemeyebilir.'),
('PG-BKP-001', 'tr', 'RECOMMENDATION', E'- PostgreSQL log''unda archive_command hatasını bulun\n- Arşiv hedefine erişilebildiğini ve boş yer olduğunu kontrol edin\n- Yedekleme aracının kendi kontrol komutunu çalıştırın (örneğin pgbackrest check)\n- Sorun çözülene kadar pg_wal dizininin büyümesini izleyin'),
('PG-BKP-001', 'tr', 'FINDING', '{node_name} üzerinde WAL arşivleme başarısız: son hata {last_failed_time} ({last_failed_wal}), son başarılı arşiv {last_archived_time}.'),
('PG-BKP-001', 'tr', 'FINDING_ALT', '{node_name} üzerinde WAL arşivleme başarısız ve kayıtlarda başarılı bir arşiv yok: son hata {last_failed_time} ({last_failed_wal}).'),
('PG-BKP-001', 'en', 'NAME', 'WAL archive failures'),
('PG-BKP-001', 'en', 'HEALTHY', 'On servers with archiving enabled, the last archive attempt succeeded.'),
('PG-BKP-001', 'en', 'MEANING', 'WAL files cannot be copied to the archive; the archive command fails.'),
('PG-BKP-001', 'en', 'CAUSES', E'- The archive destination (disk, NFS, object storage) is full or unreachable\n- The backup tool (pgBackRest, Barman, WAL-G) is misconfigured or lacks permissions\n- archive_command is wrong or calls a command missing on the server\n- The network connection to the backup server is down'),
('PG-BKP-001', 'en', 'IMPACT', 'WAL files that are not archived cannot be removed; pg_wal grows until the disk is full and PostgreSQL stops. While the problem lasts there is no point-in-time recovery; changes after the last backup may not be recoverable.'),
('PG-BKP-001', 'en', 'RECOMMENDATION', E'- Find the archive_command error in the PostgreSQL log\n- Check that the archive destination is reachable and has free space\n- Run the backup tool''s own check (for example pgbackrest check)\n- Watch the growth of pg_wal until the problem is solved'),
('PG-BKP-001', 'en', 'FINDING', 'WAL archiving is failing on {node_name}: last failure at {last_failed_time} ({last_failed_wal}), last success at {last_archived_time}.'),
('PG-BKP-001', 'en', 'FINDING_ALT', 'WAL archiving is failing on {node_name} and no successful archive is recorded: last failure at {last_failed_time} ({last_failed_wal}).'),

-- PG-TRAN-005 ---------------------------------------------------------------
('PG-TRAN-005', 'tr', 'NAME', 'Uzun bekleyen prepared transaction'),
('PG-TRAN-005', 'tr', 'HEALTHY', 'Hiçbir prepared transaction {warning} sınırından uzun süredir beklemiyor.'),
('PG-TRAN-005', 'tr', 'MEANING', 'Two-phase commit ile hazırlanmış (PREPARE TRANSACTION) bir transaction uzun süredir COMMIT PREPARED ya da ROLLBACK PREPARED bekliyor.'),
('PG-TRAN-005', 'tr', 'CAUSES', E'- Dağıtık transaction''ı yöneten uygulama ya da transaction manager çöktü\n- Uygulama bir hatadan sonra prepared transaction''ı tamamlamadı\n- Transaction manager ile veritabanı arasındaki bağlantı koptu'),
('PG-TRAN-005', 'tr', 'IMPACT', 'Transaction''ın tuttuğu lock''lar serbest kalmaz ve ilgili tablolardaki işlemler bekler. Vacuum eski satırları temizleyemez: tablolar şişer, süre uzadıkça transaction ID wraparound riski büyür. Bağlı bir session olmadığı için normal session izlemesinde görünmez.'),
('PG-TRAN-005', 'tr', 'RECOMMENDATION', E'- Transaction''ın hangi uygulamaya ya da transaction manager''a ait olduğunu bulun (gid genellikle ipucu verir)\n- Transaction manager''dan sonucu öğrenip COMMIT PREPARED ya da ROLLBACK PREPARED çalıştırın\n- Transaction manager''a sormadan rollback etmeyin; dağıtık işlemin bir kısmı geri alınırsa veri tutarsızlığı oluşur\n- Two-phase commit kullanılmıyorsa max_prepared_transactions değerini 0 yapın'),
('PG-TRAN-005', 'tr', 'FINDING', '{database_name} veritabanında {owner} kullanıcısının prepared transaction''ı ({gid}) commit ya da rollback bekliyor; bekleme süresi: {age_seconds}.'),
('PG-TRAN-005', 'en', 'NAME', 'Long prepared transaction'),
('PG-TRAN-005', 'en', 'HEALTHY', 'No prepared transaction has been waiting longer than {warning}.'),
('PG-TRAN-005', 'en', 'MEANING', 'A transaction prepared for two-phase commit (PREPARE TRANSACTION) has been waiting long for COMMIT PREPARED or ROLLBACK PREPARED.'),
('PG-TRAN-005', 'en', 'CAUSES', E'- The application or transaction manager running the distributed transaction crashed\n- The application did not finish the prepared transaction after an error\n- The connection between the transaction manager and the database was lost'),
('PG-TRAN-005', 'en', 'IMPACT', 'The locks it holds are not released and work on the affected tables waits. Vacuum cannot remove old rows: tables bloat, and the longer it waits the closer transaction ID wraparound gets. With no session attached it does not show up in normal session monitoring.'),
('PG-TRAN-005', 'en', 'RECOMMENDATION', E'- Find the application or transaction manager it belongs to (the gid usually hints at it)\n- Ask the transaction manager for the outcome, then run COMMIT PREPARED or ROLLBACK PREPARED\n- Never roll back without asking the transaction manager; undoing part of a distributed transaction leaves data inconsistent\n- If two-phase commit is not used, set max_prepared_transactions to 0'),
('PG-TRAN-005', 'en', 'FINDING', 'Prepared transaction {gid} in database {database_name} (owner {owner}) has been waiting for COMMIT or ROLLBACK for {age_seconds}.'),

-- PG-HA-001 -----------------------------------------------------------------
('PG-HA-001', 'tr', 'NAME', 'Yakın zamanda failover'),
('PG-HA-001', 'tr', 'HEALTHY', 'Yakın zamanda failover ya da switchover olmamış.'),
('PG-HA-001', 'tr', 'MEANING', 'Cluster''da yakın zamanda failover ya da switchover oldu; primary rolü başka bir sunucuya geçti.'),
('PG-HA-001', 'tr', 'CAUSES', E'- Primary sunucu çöktü, yeniden başladı ya da yanıt vermedi\n- Ağ kesintisi yüzünden HA aracı (Patroni vb.) primary''ye ulaşamadı\n- DCS (etcd, Consul) erişim sorunu leader kaydının yenilenmesini engelledi\n- Bakım için planlı bir switchover yapıldı'),
('PG-HA-001', 'tr', 'IMPACT', 'Failover sırasında bağlantılar kopar ve yazma işlemleri kısa süre durur. Asenkron replikasyonda eski primary''nin replica''lara henüz gitmemiş son transaction''ları kaybolmuş olabilir. Sebebi bilinmeyen bir failover tekrar edebilir.'),
('PG-HA-001', 'tr', 'RECOMMENDATION', E'- Failover planlı değilse eski primary''nin ve HA aracının log''larında sebebini bulun\n- Eski primary''nin cluster''a replica olarak döndüğünü kontrol edin\n- Uygulamaların yeni primary''ye bağlandığını doğrulayın\n- Asenkron replikasyon kullanılıyorsa kayıp transaction olup olmadığını değerlendirin'),
('PG-HA-001', 'tr', 'FINDING', 'Son failover ya da switchover {since_seconds} önce ({timeline_started_at}) oldu; şu anki primary {node_name}, timeline {timeline_id}.'),
('PG-HA-001', 'en', 'NAME', 'Recent failover'),
('PG-HA-001', 'en', 'HEALTHY', 'No recent failover or switchover.'),
('PG-HA-001', 'en', 'MEANING', 'A failover or switchover happened recently; the primary role moved to another server.'),
('PG-HA-001', 'en', 'CAUSES', E'- The primary crashed, restarted or stopped responding\n- A network outage kept the HA tool (Patroni etc.) from reaching the primary\n- A DCS (etcd, Consul) problem kept the leader key from being renewed\n- A planned switchover for maintenance'),
('PG-HA-001', 'en', 'IMPACT', 'During a failover connections drop and writes stop for a short time. With asynchronous replication, the last transactions of the old primary that had not reached the replicas may be lost. A failover with an unknown cause can happen again.'),
('PG-HA-001', 'en', 'RECOMMENDATION', E'- If the failover was not planned, find its cause in the logs of the old primary and the HA tool\n- Check that the old primary rejoined the cluster as a replica\n- Make sure the applications connect to the new primary\n- With asynchronous replication, assess whether transactions were lost'),
('PG-HA-001', 'en', 'FINDING', 'The last failover or switchover was {since_seconds} ago ({timeline_started_at}); the current primary is {node_name}, timeline {timeline_id}.')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
