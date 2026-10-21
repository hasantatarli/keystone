/*
===============================================================================
Migration No : 036
Version      : V036
Title        : Configuration and Connection Capacity Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the PG_CONFIGURATION_HEALTH assessment and CONFIGURATION topic with
PG-CONF-001 Pending Restart, PG-CONF-002 Unsafe Durability Settings and
PG-CONF-004 Autovacuum Disabled, and PG-CONN-002 Connection Capacity in
PG_CONNECTION_HEALTH.
===============================================================================
*/


/*
Design notes (2026-10-21, PostgreSQL V1 Assessment Catalogue, P1)
-----------------------------------------------------------------
- Configuration rules read the latest pg_settings snapshot of every node; one
  finding per node and setting.
- PG-CONF-002: fsync or full_page_writes off are CRITICAL (data corruption
  after a crash); synchronous_commit off is WARNING, a conscious choice in some
  systems (review decision 2026-10-20). Only the server-level value is seen.
- PG-CONF-004: autovacuum off, or track_counts off (autovacuum cannot work).
- PG-CONN-002: client connections on the primary against max_connections minus
  superuser_reserved_connections and reserved_connections (PostgreSQL 16+).
  The finding shows the connection count and the limit used, not only a ratio.
===============================================================================
*/


/* ============================================================================
   TOPIC AND ASSESSMENT
   ============================================================================ */

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('CONFIGURATION', 60)
ON CONFLICT (topic_key) DO NOTHING;

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name) VALUES
    ('CONFIGURATION', 'tr', 'Konfigürasyon'),
    ('CONFIGURATION', 'en', 'Configuration')
ON CONFLICT (topic_key, language_code) DO NOTHING;

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_CONFIGURATION_HEALTH', 'Configuration Health', 'PostgreSQL',
     'Evaluates PostgreSQL configuration of every node for settings that endanger data safety or maintenance.',
     3600)
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
    ('PG_CONFIGURATION_HEALTH', 'PG-CONF-001', 'Pending Restart',
     'Detects settings changed in the configuration that take effect only after a restart.',
     'PG_CONFIGURATION_SNAPSHOT', 'WARNING',
     'Setting {setting} on {node_name} was changed and waits for a restart (running value: {value}).',
     'Find out who changed the setting and why, then plan a controlled restart or revert the change.',
     'CONFIGURATION'),
    ('PG_CONFIGURATION_HEALTH', 'PG-CONF-002', 'Unsafe Durability Settings',
     'Detects settings that trade crash safety for speed: fsync, full_page_writes, synchronous_commit.',
     'PG_CONFIGURATION_SNAPSHOT', NULL,
     'Setting {setting} is {value} on {node_name}.',
     'Turn fsync and full_page_writes back on. Keep synchronous_commit off only where losing the last transactions after a crash is acceptable, and document it.',
     'CONFIGURATION'),
    ('PG_CONFIGURATION_HEALTH', 'PG-CONF-004', 'Autovacuum Disabled',
     'Detects autovacuum switched off, or track_counts off, which stops autovacuum.',
     'PG_CONFIGURATION_SNAPSHOT', 'CRITICAL',
     'Setting {setting} is {value} on {node_name}; autovacuum does not run.',
     'Turn autovacuum and track_counts back on. If autovacuum was turned off for performance, tune it per table instead.',
     'CONFIGURATION'),
    ('PG_CONNECTION_HEALTH', 'PG-CONN-002', 'Connection Capacity',
     'Detects client connections approaching the usable connection slots of the primary.',
     'PG_CONNECTION_ACTIVITY', NULL,
     '{connections} of {usable} usable connections are in use ({percent}%).',
     'Find which applications hold the connections and whether they are idle. Use a connection pooler before raising max_connections.',
     'CONNECTIONS')
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
    ('WARNING',  80, 'PERCENT'),
    ('CRITICAL', 90, 'PERCENT')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-CONN-002'
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, TRUE, r.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-CONF-001', 'PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG-CONF-002', 'PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG-CONF-004', 'PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG-CONN-002', 'PG_CONNECTION_ACTIVITY',    600),
    ('PG-CONN-002', 'PG_CONFIGURATION_SNAPSHOT', 86400),
    ('PG-CONN-002', 'PG_INSTANCE_INVENTORY',     3600)
) AS r (rule_key, evidence_source, max_age_seconds) ON r.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;


/* ============================================================================
   IMPACT CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-CONF-001', 'AVAILABILITY'),
    ('PG-CONF-002', 'DATA_SAFETY'),
    ('PG-CONF-004', 'PERFORMANCE'),
    ('PG-CONF-004', 'CAPACITY'),
    ('PG-CONF-004', 'AVAILABILITY'),
    ('PG-CONN-002', 'CAPACITY'),
    ('PG-CONN-002', 'AVAILABILITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-CONF-001 ---------------------------------------------------------------
('PG-CONF-001', 'tr', 'NAME', 'Restart bekleyen ayar'),
('PG-CONF-001', 'tr', 'HEALTHY', 'Uygulanması için restart bekleyen ayar değişikliği yok.'),
('PG-CONF-001', 'tr', 'MEANING', 'Bir ayar konfigürasyonda değiştirilmiş ama ancak PostgreSQL yeniden başlatılınca devreye girecek; şu anda eski değer geçerli.'),
('PG-CONF-001', 'tr', 'CAUSES', E'- Ayar değiştirildi ama planlı restart henüz yapılmadı\n- Değişiklik bir HA aracı ya da otomasyon tarafından yapıldı ve kimse fark etmedi\n- Değişiklik unutuldu'),
('PG-CONF-001', 'tr', 'IMPACT', 'Bir sonraki restart''ta, belki bir arıza ya da failover sırasında, beklenmeyen bir ayar devreye girer; sorun çıkarsa sebebi geç anlaşılır. Değişiklik bilerek yapıldıysa, istenen etki restart''a kadar oluşmaz.'),
('PG-CONF-001', 'tr', 'RECOMMENDATION', E'- Ayarı kimin, neden değiştirdiğini belirleyin (pg_file_settings yeni değeri gösterir)\n- Değişiklik isteniyorsa kontrollü bir restart planlayın\n- İstenmiyorsa değişikliği geri alın'),
('PG-CONF-001', 'en', 'NAME', 'Setting waiting for a restart'),
('PG-CONF-001', 'en', 'HEALTHY', 'No setting change is waiting for a restart.'),
('PG-CONF-001', 'en', 'MEANING', 'A setting was changed in the configuration but takes effect only when PostgreSQL restarts; the old value is still in use.'),
('PG-CONF-001', 'en', 'CAUSES', E'- The setting was changed and the planned restart has not happened yet\n- An HA tool or automation made the change and nobody noticed\n- The change was forgotten'),
('PG-CONF-001', 'en', 'IMPACT', 'At the next restart, perhaps during a failure or failover, an unexpected setting takes effect; if it causes problems, the reason is found late. If the change was intended, it has no effect until the restart.'),
('PG-CONF-001', 'en', 'RECOMMENDATION', E'- Find out who changed the setting and why (pg_file_settings shows the new value)\n- If the change is wanted, plan a controlled restart\n- If not, revert it'),

-- PG-CONF-002 ---------------------------------------------------------------
('PG-CONF-002', 'tr', 'NAME', 'Güvenli olmayan dayanıklılık ayarları'),
('PG-CONF-002', 'tr', 'HEALTHY', 'fsync ve full_page_writes açık; synchronous_commit kapatılmamış.'),
('PG-CONF-002', 'tr', 'MEANING', 'Hız için çökme güvenliğinden ödün veren bir ayar kapatılmış.'),
('PG-CONF-002', 'tr', 'CAUSES', E'- Toplu veri yüklemesi için kapatılıp tekrar açılmamış\n- Test ya da geliştirme ortamının ayarları üretime taşınmış\n- Yazma performansı için bilerek kapatılmış (synchronous_commit)'),
('PG-CONF-002', 'tr', 'IMPACT', 'fsync ya da full_page_writes kapalıyken bir elektrik kesintisi veya işletim sistemi çökmesi veritabanını bozabilir; veri kurtarılamayabilir. synchronous_commit kapalıyken çökmede son birkaç yüz milisaniyedeki commit''ler kaybolabilir, ama veritabanı bozulmaz.'),
('PG-CONF-002', 'tr', 'RECOMMENDATION', E'- fsync ve full_page_writes ayarlarını hemen açın\n- synchronous_commit kapalıysa bunun bilinçli bir karar olup olmadığını doğrulayın ve belgeleyin\n- Gerekiyorsa synchronous_commit''i yalnızca belirli kullanıcı ya da işlemler için kapatın'),
('PG-CONF-002', 'en', 'NAME', 'Unsafe durability settings'),
('PG-CONF-002', 'en', 'HEALTHY', 'fsync and full_page_writes are on; synchronous_commit is not turned off.'),
('PG-CONF-002', 'en', 'MEANING', 'A setting that trades crash safety for speed is turned off.'),
('PG-CONF-002', 'en', 'CAUSES', E'- It was turned off for a bulk load and not turned back on\n- Settings of a test or development environment were carried to production\n- It was turned off on purpose for write performance (synchronous_commit)'),
('PG-CONF-002', 'en', 'IMPACT', 'With fsync or full_page_writes off, a power loss or operating system crash can corrupt the database beyond recovery. With synchronous_commit off, a crash can lose the commits of the last few hundred milliseconds, but the database is not corrupted.'),
('PG-CONF-002', 'en', 'RECOMMENDATION', E'- Turn fsync and full_page_writes back on immediately\n- If synchronous_commit is off, confirm that this is a conscious decision and document it\n- If needed, turn synchronous_commit off only for specific users or transactions'),

-- PG-CONF-004 ---------------------------------------------------------------
('PG-CONF-004', 'tr', 'NAME', 'Autovacuum kapalı'),
('PG-CONF-004', 'tr', 'HEALTHY', 'Autovacuum ve istatistik toplama (track_counts) açık.'),
('PG-CONF-004', 'tr', 'MEANING', 'Autovacuum kapatılmış ya da çalışması için gereken istatistik toplama (track_counts) kapalı; otomatik bakım yapılmıyor.'),
('PG-CONF-004', 'tr', 'CAUSES', E'- Performans sorununa çözüm olarak kapatılmış\n- Toplu bir iş için kapatılıp tekrar açılmamış\n- Bakımın elle (zamanlanmış VACUUM) yapıldığı düşünülmüş'),
('PG-CONF-004', 'tr', 'IMPACT', 'Silinen ve güncellenen kayıtların eski sürümleri temizlenmez: tablolar şişer, sorgular yavaşlar, istatistikler eskir. En kötü durumda transaction ID sınırına ulaşılır ve PostgreSQL yazmayı durdurur.'),
('PG-CONF-004', 'tr', 'RECOMMENDATION', E'- autovacuum ve track_counts ayarlarını açın\n- Autovacuum performans için kapatıldıysa tablo bazında ayarlayın (autovacuum_vacuum_cost_limit, tablo ayarları)\n- Açtıktan sonra şişmiş tabloları ve transaction ID yaşını kontrol edin'),
('PG-CONF-004', 'en', 'NAME', 'Autovacuum disabled'),
('PG-CONF-004', 'en', 'HEALTHY', 'Autovacuum and statistics collection (track_counts) are on.'),
('PG-CONF-004', 'en', 'MEANING', 'Autovacuum is turned off, or the statistics collection it needs (track_counts) is off; no automatic maintenance runs.'),
('PG-CONF-004', 'en', 'CAUSES', E'- It was turned off as a fix for a performance problem\n- It was turned off for a batch job and not turned back on\n- Maintenance was assumed to run by hand (scheduled VACUUM)'),
('PG-CONF-004', 'en', 'IMPACT', 'Old versions of deleted and updated rows are not removed: tables bloat, queries slow down, statistics become stale. In the worst case the transaction ID limit is reached and PostgreSQL stops accepting writes.'),
('PG-CONF-004', 'en', 'RECOMMENDATION', E'- Turn autovacuum and track_counts back on\n- If autovacuum was turned off for performance, tune it per table instead (autovacuum_vacuum_cost_limit, table settings)\n- After turning it on, check bloated tables and transaction ID age'),

-- PG-CONN-002 ---------------------------------------------------------------
('PG-CONN-002', 'tr', 'NAME', 'Bağlantı kapasitesi'),
('PG-CONN-002', 'tr', 'HEALTHY', 'Kullanılan bağlantı sayısı, kullanılabilir bağlantıların {warning} sınırına ulaşmamış.'),
('PG-CONN-002', 'tr', 'MEANING', 'Primary''de kullanılan bağlantı sayısı, kullanılabilir bağlantı sınırına yaklaşıyor.'),
('PG-CONN-002', 'tr', 'CAUSES', E'- Uygulamalar bağlantıları kapatmıyor ya da gereğinden fazla açıyor\n- Connection pooler yok; her istek ayrı bağlantı açıyor\n- Yavaşlayan sorgular yüzünden bağlantılar uzun süre meşgul kalıyor\n- Uygulama sunucusu sayısı artmış'),
('PG-CONN-002', 'tr', 'IMPACT', 'Sınır dolduğunda yeni bağlantılar "too many clients" hatasıyla reddedilir; uygulama veritabanına bağlanamaz.'),
('PG-CONN-002', 'tr', 'RECOMMENDATION', E'- Bağlantıların hangi uygulama ve kullanıcılara ait olduğunu ve ne kadarının boşta beklediğini belirleyin\n- PgBouncer gibi bir connection pooler kullanın\n- max_connections''ı artırmadan önce bellek etkisini hesaplayın; her bağlantı bellek kullanır'),
('PG-CONN-002', 'en', 'NAME', 'Connection capacity'),
('PG-CONN-002', 'en', 'HEALTHY', 'Connections in use have not reached {warning} of the usable connections.'),
('PG-CONN-002', 'en', 'MEANING', 'The number of connections in use on the primary is approaching the usable connection limit.'),
('PG-CONN-002', 'en', 'CAUSES', E'- Applications do not close connections or open more than needed\n- There is no connection pooler; every request opens its own connection\n- Slow queries keep connections busy for long\n- The number of application servers has grown'),
('PG-CONN-002', 'en', 'IMPACT', 'When the limit is reached, new connections are refused with "too many clients"; applications cannot connect to the database.'),
('PG-CONN-002', 'en', 'RECOMMENDATION', E'- Find which applications and users hold the connections and how many are idle\n- Use a connection pooler such as PgBouncer\n- Before raising max_connections, calculate the memory impact; every connection uses memory')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
