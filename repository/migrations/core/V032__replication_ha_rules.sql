/*
===============================================================================
Migration No : 032
Version      : V032
Title        : Replication and HA Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds four rules to PG_REPLICATION_HEALTH: PG-REP-003 Replication Lag,
PG-REP-004 Replica Not Streaming, PG-REP-005 Inactive Replication Slot and
PG-REP-006 Synchronous Replication Without a Synchronous Standby. Makes the
schedule consistency view aware of NODE-scoped evidence.
===============================================================================
*/


/*
Design notes (2026-10-20, PostgreSQL V1 Assessment Catalogue, P1)
-----------------------------------------------------------------
- PG-REP-003 measures replay lag in time. replay_lag is NULL when a replica
  has caught up and the primary is idle; that is no lag.
- PG-REP-004 compares the nodes Keystone knows as replicas (instance
  inventory, in recovery) with pg_stat_replication on the primary, matched by
  address. Cascading replicas connected to another replica are not visible on
  the primary and would be reported; documented in the Rule Catalog.
- PG-REP-006 uses synchronous_standby_names captured with the replication
  status on the same server at the same moment (PG014).
===============================================================================
*/


/* ============================================================================
   RULE DEFINITIONS
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
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source,
       r.default_severity, r.finding_template, r.recommendation, 'REPLICATION'
FROM keystone.assessment_definition ad
CROSS JOIN (VALUES
    ('PG-REP-003', 'Replication Lag',
     'Detects replicas that replay changes later than the configured thresholds.',
     'PG_REPLICATION_STATUS', NULL,
     'Replica {replica} is {lag_seconds} seconds behind the primary in replaying changes.',
     'Separate where the lag comes from: write/flush lag points to the network or the replica''s disk, replay lag alone to load or long queries on the replica. Review the replica''s resources and hot_standby_feedback / max_standby_streaming_delay.'),
    ('PG-REP-004', 'Replica Not Streaming',
     'Detects nodes known as replicas that are not streaming from the primary.',
     'PG_REPLICATION_STATUS', 'WARNING',
     'Replica {replica} is not streaming from the primary (state: {state}).',
     'Check that the replica server and PostgreSQL are running, that it can reach the primary, and the replication errors in the PostgreSQL logs. If an HA tool such as Patroni is used, review its state (patronictl list).'),
    ('PG-REP-005', 'Inactive Replication Slot',
     'Detects permanent replication slots without a connected consumer.',
     'PG_REPLICATION_SLOTS', 'WARNING',
     'Replication slot {slot_name} ({slot_type}) is not in use.',
     'Identify who owns the slot. If its consumer will not come back, drop it (pg_drop_replication_slot); otherwise watch the retained WAL. max_slot_wal_keep_size can set an upper limit.'),
    ('PG-REP-006', 'Synchronous Replication Without a Synchronous Standby',
     'Detects synchronous replication configured while no standby is synchronous, so commits wait.',
     'PG_REPLICATION_STATUS', 'CRITICAL',
     'Synchronous replication is configured (synchronous_standby_names = {synchronous_standby_names}) but no standby is synchronous; commits wait for a confirmation that cannot come.',
     'Bring a standby back. In an emergency, emptying synchronous_standby_names (ALTER SYSTEM and reload) lets writes continue but removes the synchronous durability guarantee. With Patroni, check the synchronous_mode settings.')
) AS r (rule_key, name, description, evidence_source, default_severity, finding_template, recommendation)
WHERE ad.assessment_key = 'PG_REPLICATION_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   RULE THRESHOLDS
   ============================================================================ */

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, t.threshold_unit
FROM keystone.rule_definition rd
CROSS JOIN (VALUES
    ('WARNING',  60,  'SECOND'),
    ('CRITICAL', 300, 'SECOND')
) AS t (severity, threshold_value, threshold_unit)
WHERE rd.rule_key = 'PG-REP-003'
ON CONFLICT (rule_id, severity) DO NOTHING;


/* ============================================================================
   EVIDENCE REQUIREMENTS
   ============================================================================ */

-- Instance inventory: replica roles change rarely, but must be recent after a failover.
INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, r.evidence_source, TRUE, r.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-REP-003', 'PG_REPLICATION_STATUS', 600),
    ('PG-REP-004', 'PG_REPLICATION_STATUS', 600),
    ('PG-REP-004', 'PG_INSTANCE_INVENTORY', 3600),
    ('PG-REP-005', 'PG_REPLICATION_SLOTS',  600),
    ('PG-REP-006', 'PG_REPLICATION_STATUS', 600)
) AS r (rule_key, evidence_source, max_age_seconds) ON r.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;


/* ============================================================================
   IMPACT CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-REP-003', 'AVAILABILITY'),
    ('PG-REP-003', 'DATA_SAFETY'),
    ('PG-REP-004', 'AVAILABILITY'),
    ('PG-REP-004', 'DATA_SAFETY'),
    ('PG-REP-005', 'CAPACITY'),
    ('PG-REP-005', 'AVAILABILITY'),
    ('PG-REP-006', 'AVAILABILITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-REP-003 ----------------------------------------------------------------
('PG-REP-003', 'tr', 'NAME', 'Replikasyon gecikmesi'),
('PG-REP-003', 'tr', 'HEALTHY',
 'Bağlı replica''ların hiçbiri değişiklikleri {warning} ya da daha geriden uygulamıyor.'),
('PG-REP-003', 'tr', 'MEANING',
 'Replica, primary''de yapılan değişiklikleri geriden uyguluyor. Sebep genellikle ağ yavaşlığı, replica''nın disk ya da CPU yetersizliği, replica''da uzun süren sorguların uygulamayı bekletmesi ya da primary''deki yoğun yazma yüküdür.'),
('PG-REP-003', 'tr', 'IMPACT',
 'Replica''dan okuyan uygulamalar eski veri görür. Failover gerekirse replica önce birikmiş değişiklikleri uygulamak zorunda kalır; geçiş uzar.'),
('PG-REP-003', 'tr', 'RECOMMENDATION',
 'Gecikmenin nereden geldiğini ayırın: write/flush gecikmesi ağı ya da replica''nın diskini, yalnızca replay gecikmesi replica''daki yükü ya da uzun sorguları gösterir. Replica''nın kaynaklarını ve hot_standby_feedback / max_standby_streaming_delay ayarlarını gözden geçirin.'),
('PG-REP-003', 'en', 'NAME', 'Replication lag'),
('PG-REP-003', 'en', 'HEALTHY',
 'No connected replica replays changes {warning} or more behind the primary.'),
('PG-REP-003', 'en', 'MEANING',
 'A replica applies the primary''s changes late. The usual causes are a slow network, too little disk or CPU on the replica, long queries on the replica holding back replay, or heavy write load on the primary.'),
('PG-REP-003', 'en', 'IMPACT',
 'Applications reading from the replica see old data. If a failover is needed, the replica must first apply the backlog, so the switch takes longer.'),
('PG-REP-003', 'en', 'RECOMMENDATION',
 'Separate where the lag comes from: write/flush lag points to the network or the replica''s disk, replay lag alone to load or long queries on the replica. Review the replica''s resources and hot_standby_feedback / max_standby_streaming_delay.'),

-- PG-REP-004 ----------------------------------------------------------------
('PG-REP-004', 'tr', 'NAME', 'Primary''den veri almayan replica'),
('PG-REP-004', 'tr', 'HEALTHY',
 'Replica olarak bilinen tüm sunucular primary''ye bağlı ve değişiklikleri alıyor.'),
('PG-REP-004', 'tr', 'MEANING',
 'Replica olarak bilinen bir sunucu primary''den değişiklik almıyor: kapalı, ağ üzerinden ulaşılamıyor, replikasyon bağlantısı kopmuş ya da hâlâ başlangıç veya yakalama aşamasında.'),
('PG-REP-004', 'tr', 'IMPACT',
 'O replica güncel değil; failover gerekirse geçilebilecek sağlıklı sunucu sayısı azalır. Hiçbir replica bağlı değilse sistemin yedeği kalmamıştır: primary''deki bir arıza kesintiye ve veri kaybına yol açar.'),
('PG-REP-004', 'tr', 'RECOMMENDATION',
 'Replica sunucusunun ve PostgreSQL servisinin çalıştığını, primary''ye ağ erişimini ve PostgreSQL loglarındaki replikasyon hatalarını kontrol edin. Patroni gibi bir HA aracı varsa durumunu (patronictl list) inceleyin.'),
('PG-REP-004', 'en', 'NAME', 'Replica not receiving changes'),
('PG-REP-004', 'en', 'HEALTHY',
 'Every server known as a replica is connected to the primary and receiving changes.'),
('PG-REP-004', 'en', 'MEANING',
 'A server known as a replica is not receiving changes from the primary: it is down, unreachable over the network, its replication connection broke, or it is still starting up or catching up.'),
('PG-REP-004', 'en', 'IMPACT',
 'That replica is not current; fewer healthy servers are available for a failover. If no replica is connected the system has no standby left: a failure of the primary means downtime and data loss.'),
('PG-REP-004', 'en', 'RECOMMENDATION',
 'Check that the replica server and PostgreSQL are running, that it can reach the primary, and the replication errors in the PostgreSQL logs. If an HA tool such as Patroni is used, review its state (patronictl list).'),

-- PG-REP-005 ----------------------------------------------------------------
('PG-REP-005', 'tr', 'NAME', 'Kullanılmayan replication slot'),
('PG-REP-005', 'tr', 'HEALTHY',
 'Kullanılmayan (inaktif) kalıcı replication slot yok.'),
('PG-REP-005', 'tr', 'MEANING',
 'Bir replication slot tanımlı ama şu anda ona bağlı bir replica ya da logical replication tüketicisi yok. Genellikle kapatılmış ya da kaldırılmış bir replica''nın, silinmemiş bir aboneliğin ya da durmuş bir CDC aracının slot''udur.'),
('PG-REP-005', 'tr', 'IMPACT',
 'PostgreSQL, slot''un tüketicisi geri gelene kadar gereken WAL dosyalarını silmez; disk dolabilir. Logical slot''lar ayrıca vacuum''un eski kayıtları temizlemesini engelleyebilir.'),
('PG-REP-005', 'tr', 'RECOMMENDATION',
 'Slot''un kime ait olduğunu belirleyin. Tüketicisi geri gelmeyecekse slot''u silin (pg_drop_replication_slot); gelecekse biriken WAL''ı izleyin. max_slot_wal_keep_size ile bir üst sınır tanımlanabilir.'),
('PG-REP-005', 'en', 'NAME', 'Unused replication slot'),
('PG-REP-005', 'en', 'HEALTHY',
 'No permanent replication slot is inactive.'),
('PG-REP-005', 'en', 'MEANING',
 'A replication slot exists but no replica or logical replication consumer is connected to it. It usually belongs to a replica that was shut down or removed, a subscription that was not dropped, or a stopped CDC tool.'),
('PG-REP-005', 'en', 'IMPACT',
 'PostgreSQL keeps the WAL the slot needs until its consumer returns; the disk can fill up. Logical slots can also stop vacuum from removing old rows.'),
('PG-REP-005', 'en', 'RECOMMENDATION',
 'Identify who owns the slot. If its consumer will not come back, drop it (pg_drop_replication_slot); otherwise watch the retained WAL. max_slot_wal_keep_size can set an upper limit.'),

-- PG-REP-006 ----------------------------------------------------------------
('PG-REP-006', 'tr', 'NAME', 'Synchronous standby olmadan synchronous replikasyon'),
('PG-REP-006', 'tr', 'HEALTHY',
 'Synchronous replikasyon tanımlı değil ya da tanımlıysa en az bir standby synchronous durumda.'),
('PG-REP-006', 'tr', 'MEANING',
 'Primary''de synchronous replikasyon tanımlı (synchronous_standby_names), ama şu anda synchronous durumda olan bir standby yok.'),
('PG-REP-006', 'tr', 'IMPACT',
 'Primary her commit''te bir synchronous standby''nin onayını bekler. Onay verecek standby olmadığı için yazma işlemleri tamamlanmaz; uygulama için veritabanı yazmaya kapanmış gibidir.'),
('PG-REP-006', 'tr', 'RECOMMENDATION',
 'Standby''ların neden bağlı olmadığını giderin. Acil durumda synchronous_standby_names boşaltılarak (ALTER SYSTEM ve reload) yazma açılabilir; bu, synchronous replikasyonun veri güvenliği garantisini geçici olarak kaldırır. Patroni kullanılıyorsa synchronous_mode ayarlarını kontrol edin.'),
('PG-REP-006', 'en', 'NAME', 'Synchronous replication without a synchronous standby'),
('PG-REP-006', 'en', 'HEALTHY',
 'Synchronous replication is not configured, or at least one standby is synchronous.'),
('PG-REP-006', 'en', 'MEANING',
 'Synchronous replication is configured on the primary (synchronous_standby_names) but no standby is currently synchronous.'),
('PG-REP-006', 'en', 'IMPACT',
 'The primary waits for a synchronous standby to confirm every commit. With no standby to confirm, writes do not complete; for applications the database is closed for writing.'),
('PG-REP-006', 'en', 'RECOMMENDATION',
 'Find out why the standbys are not connected. In an emergency, emptying synchronous_standby_names (ALTER SYSTEM and reload) lets writes continue but temporarily removes the durability guarantee of synchronous replication. With Patroni, check the synchronous_mode settings.')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;


/* ============================================================================
   CONSISTENCY VIEW: NODE-SCOPED EVIDENCE
   ============================================================================ */

-- NODE-scoped collectors (host, configuration, instance inventory) run on the
-- NODE children of a SYSTEM target, not on the target the assessment runs for.
CREATE OR REPLACE VIEW keystone.schedule_consistency_warning AS
SELECT
    s.target_id,
    t.name                AS target_name,
    ad.assessment_key,
    rd.rule_key,
    rer.evidence_source,
    CASE
        WHEN ca.assignment_id IS NULL THEN 'NOT_SCHEDULED'
        ELSE 'INTERVAL_TOO_LONG'
    END                   AS problem,
    ca.interval_seconds   AS collector_interval_seconds,
    rer.max_age_seconds,
    CASE
        WHEN ca.assignment_id IS NULL THEN
            format('Collector %s is not scheduled for this target; the rule will end INSUFFICIENT_EVIDENCE.',
                   rer.evidence_source)
        ELSE
            format('Collector %s runs every %s s but the rule needs evidence not older than %s s.',
                   rer.evidence_source, ca.interval_seconds, rer.max_age_seconds)
    END                   AS detail
FROM keystone.assessment_schedule s
JOIN keystone.target t
    ON t.target_id = s.target_id
JOIN keystone.assessment_definition ad
    ON ad.assessment_id = s.assessment_id
JOIN keystone.rule_definition rd
    ON rd.assessment_id = ad.assessment_id
JOIN keystone.rule_evidence_requirement rer
    ON rer.rule_id = rd.rule_id
LEFT JOIN LATERAL
(
    SELECT ca.assignment_id, ca.interval_seconds
    FROM keystone.collector_assignment ca
    JOIN keystone.collector_definition cd
        ON cd.collector_id = ca.collector_id
    JOIN keystone.target ct
        ON ct.target_id = ca.target_id
    WHERE (ca.target_id = s.target_id
           OR (cd.execution_scope = 'NODE' AND ct.parent_target_id = s.target_id
               AND ct.target_type = 'NODE' AND ct.is_active))
      AND cd.collector_key = rer.evidence_source
      AND ca.execution_mode = 'SCHEDULED'
      AND ca.is_enabled
      AND cd.is_active
    ORDER BY ca.interval_seconds
    LIMIT 1
) ca ON TRUE
WHERE s.is_enabled
  AND t.is_active
  AND ad.is_enabled
  AND rd.is_enabled
  AND rer.is_required
  AND
  (
      ca.assignment_id IS NULL
      OR (rer.max_age_seconds IS NOT NULL AND ca.interval_seconds > rer.max_age_seconds)
  );
