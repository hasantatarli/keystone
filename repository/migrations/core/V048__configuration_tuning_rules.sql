/*
===============================================================================
Migration No : 048
Version      : V048
Title        : Configuration Tuning Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
ADR-0017 step 3a: assessment PG_CONFIGURATION_TUNING with PG-CONF-003 Setting
Outside Recommendation (INFO) and PG-CONF-007 Memory Overcommitment
(CRITICAL), and keystone.config_recommendation for the result of every
recommendation of a run.
===============================================================================
*/


/*
Design notes (2026-11-02, Hasan)
--------------------------------
- Recommendations are for the whole system, computed from the smallest node
  (memory, CPUs, data disk); the current value is the primary's, other nodes
  with a different value are noted.
- A setting outside its range is a recommendation, not a problem: INFO. The
  executive part shows only real risk; the memory commitment is that risk.
- Without host data the settings that need memory, CPUs or the disk are not
  assessed (named per setting); the others still are. The rule is
  INSUFFICIENT_EVIDENCE only when no setting could be assessed.
- PG-CONF-007 uses physical memory, not the non-dedicated share: the OOM
  killer acts on physical memory. The formula is pessimistic (not every
  connection uses work_mem at once) but a query can also use it several times.
- Only results are stored; the inputs stay in the collected snapshots and the
  check's target_profile. The same raw data gives other results under other
  Dictionary numbers.
===============================================================================
*/


/* ============================================================================
   RESULT TABLE
   ============================================================================ */

CREATE TABLE keystone.config_recommendation
(
    config_recommendation_id  BIGINT GENERATED ALWAYS AS IDENTITY,
    assessment_result_id      BIGINT       NOT NULL,
    setting_key               VARCHAR(64)  NOT NULL,
    group_key                 VARCHAR(20)  NOT NULL,
    value_type                VARCHAR(10)  NOT NULL,
    status                    VARCHAR(20)  NOT NULL,
    current_value             TEXT,        -- primary's value in Keystone units (bytes, seconds) or the word
    recommended_value         TEXT,
    acceptable                JSONB,       -- {"low", "high"} or {"values": [...]}
    calculation               JSONB,       -- {"method", values...}: the report writes the sentence
    reason_code               VARCHAR(40), -- why NOT_ASSESSED / NOT_APPLICABLE
    parameters_used           JSONB,       -- Dictionary numbers applied
    node_differences          JSONB,       -- [{"node", "value"}] where another node differs

    CONSTRAINT pk_config_recommendation PRIMARY KEY (config_recommendation_id),
    CONSTRAINT fk_config_recommendation_result
        FOREIGN KEY (assessment_result_id) REFERENCES keystone.assessment_result (assessment_result_id),
    CONSTRAINT uq_config_recommendation UNIQUE (assessment_result_id, setting_key),
    CONSTRAINT ck_config_recommendation_status
        CHECK (status IN ('FITS', 'DEVIATES', 'NOT_ASSESSED', 'NOT_APPLICABLE'))
);

COMMENT ON TABLE keystone.config_recommendation IS
'Result of every configuration recommendation of a PG-CONF-003 evaluation (ADR-0017): what the customer was told.';


/* ============================================================================
   ASSESSMENT AND RULES
   ============================================================================ */

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_CONFIGURATION_TUNING', 'Configuration Tuning', 'PostgreSQL',
     'Compares settings with values recommended for the server''s memory, CPUs, storage and workload.', 86400)
ON CONFLICT (assessment_key) DO NOTHING;

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source,
       r.default_severity, r.finding_template, r.recommendation, r.topic_key
FROM (VALUES
    ('PG-CONF-003', 'Setting Outside Recommendation',
     'Compares settings with the values recommended for this server and reports those outside the acceptable range.',
     'PG_CONFIGURATION_SNAPSHOT', 'INFO',
     '{setting} is {current}; recommended for this server: {recommended} (acceptable: {acceptable}).',
     'Review the setting with the recommendation and its reason; change it if no deliberate choice explains the difference.',
     'CONFIGURATION'),
    ('PG-CONF-007', 'Memory Overcommitment',
     'Detects servers whose shared_buffers plus max_connections times work_mem exceeds their memory.',
     'PG_CONFIGURATION_SNAPSHOT', 'CRITICAL',
     'On {node} shared_buffers ({shared_buffers}) plus max_connections × work_mem ({max_connections} × {work_mem}) is {committed}, more than its memory ({memory}).',
     'Lower work_mem or max_connections (a connection pooler lets fewer connections serve the same clients), or add memory.',
     'CONFIGURATION')
) AS r (rule_key, name, description, evidence_source, default_severity, finding_template,
        recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = 'PG_CONFIGURATION_TUNING'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, e.evidence_source, e.is_required, e.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-CONF-003', 'PG_CONFIGURATION_SNAPSHOT', TRUE,  86400),
    ('PG-CONF-003', 'PG_INSTANCE_INVENTORY',     TRUE,  3600),
    ('PG-CONF-003', 'PG_HOST_SNAPSHOT',          FALSE, 86400),
    ('PG-CONF-007', 'PG_CONFIGURATION_SNAPSHOT', TRUE,  86400),
    ('PG-CONF-007', 'PG_HOST_SNAPSHOT',          TRUE,  86400)
) AS e (rule_key, evidence_source, is_required, max_age_seconds) ON e.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-CONF-003', 'PERFORMANCE'),
    ('PG-CONF-007', 'AVAILABILITY'),
    ('PG-CONF-007', 'CAPACITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-CONF-003', 'tr', 'NAME', 'Öneriden farklı ayar'),
('PG-CONF-003', 'tr', 'HEALTHY', 'Değerlendirilen ayarların hepsi bu sunucu için önerilen aralıkta.'),
('PG-CONF-003', 'tr', 'MEANING', 'Bazı ayarlar bu sunucunun belleği, CPU sayısı, disk tipi ve iş yükü için önerilen aralığın dışında.'),
('PG-CONF-003', 'tr', 'CAUSES', E'- Ayarlar kurulumdaki varsayılan değerlerde kalmış\n- Sunucunun belleği, CPU''su ya da diski değişmiş, ayarlar güncellenmemiş\n- Ayar bilinçli olarak farklı seçilmiş (özel bir iş yükü için)'),
('PG-CONF-003', 'tr', 'IMPACT', 'Sunucu kaynaklarını tam kullanamaz ya da gereğinden fazla zorlanır; sorgular yavaşlayabilir, bakım işlemleri uzayabilir.'),
('PG-CONF-003', 'tr', 'RECOMMENDATION', E'- Her ayarı önerisi ve gerekçesiyle birlikte gözden geçirin\n- Bilinçli bir seçim değilse önerilen değere getirin; restart gerektiren ayarları bakım penceresinde değiştirin'),
('PG-CONF-003', 'tr', 'FINDING', '{setting} şu an {current}; bu sunucu için önerilen {recommended} (kabul edilebilir: {acceptable}).'),
('PG-CONF-003', 'en', 'NAME', 'Setting outside recommendation'),
('PG-CONF-003', 'en', 'HEALTHY', 'Every setting assessed is within the range recommended for this server.'),
('PG-CONF-003', 'en', 'MEANING', 'Some settings are outside the range recommended for this server''s memory, CPUs, storage type and workload.'),
('PG-CONF-003', 'en', 'CAUSES', E'- Settings were left at the installation defaults\n- The server''s memory, CPUs or disk changed and the settings were not updated\n- The setting was chosen deliberately (for a particular workload)'),
('PG-CONF-003', 'en', 'IMPACT', 'The server cannot use its resources fully, or is strained more than necessary; queries can slow down and maintenance can take longer.'),
('PG-CONF-003', 'en', 'RECOMMENDATION', E'- Review each setting with its recommendation and reason\n- Unless it is a deliberate choice, set the recommended value; change settings that need a restart in a maintenance window'),
('PG-CONF-003', 'en', 'FINDING', '{setting} is {current}; recommended for this server: {recommended} (acceptable: {acceptable}).'),

('PG-CONF-007', 'tr', 'NAME', 'Bellek aşırı taahhüdü'),
('PG-CONF-007', 'tr', 'HEALTHY', 'shared_buffers ile bütün bağlantıların work_mem toplamı hiçbir sunucunun belleğini aşmıyor.'),
('PG-CONF-007', 'tr', 'MEANING', 'shared_buffers ile max_connections × work_mem toplamı sunucunun belleğinden büyük.'),
('PG-CONF-007', 'tr', 'CAUSES', E'- work_mem bağlantı sayısı düşünülmeden yükseltilmiş\n- max_connections connection pool yerine yüksek tutulmuş\n- Ayarlar daha büyük bir sunucudan kopyalanmış'),
('PG-CONF-007', 'tr', 'IMPACT', 'Yoğun anda bağlantılar aynı anda bellek istediğinde işletim sistemi PostgreSQL süreçlerini sonlandırabilir (OOM killer); bu tüm veritabanının yeniden başlaması demektir.'),
('PG-CONF-007', 'tr', 'RECOMMENDATION', E'- work_mem''i düşürün; büyük sorgular için session bazında yükseltin\n- Bağlantı sayısını bir connection pool (PgBouncer gibi) ile azaltın\n- Gerekirse sunucuya bellek ekleyin'),
('PG-CONF-007', 'tr', 'FINDING', '{node} sunucusunda shared_buffers ({shared_buffers}) ile max_connections × work_mem ({max_connections} × {work_mem}) toplamı {committed}; sunucunun belleği ({memory}) bundan küçük.'),
('PG-CONF-007', 'en', 'NAME', 'Memory overcommitment'),
('PG-CONF-007', 'en', 'HEALTHY', 'shared_buffers plus work_mem for every connection does not exceed the memory of any server.'),
('PG-CONF-007', 'en', 'MEANING', 'shared_buffers plus max_connections × work_mem is larger than the server''s memory.'),
('PG-CONF-007', 'en', 'CAUSES', E'- work_mem was raised without regard to the number of connections\n- max_connections is kept high instead of using a connection pool\n- Settings were copied from a larger server'),
('PG-CONF-007', 'en', 'IMPACT', 'At peak, when connections ask for memory together, the operating system can kill PostgreSQL processes (OOM killer), which restarts the whole database.'),
('PG-CONF-007', 'en', 'RECOMMENDATION', E'- Lower work_mem; raise it per session for large queries\n- Reduce connections with a connection pool such as PgBouncer\n- Add memory if needed'),
('PG-CONF-007', 'en', 'FINDING', 'On {node} shared_buffers ({shared_buffers}) plus max_connections × work_mem ({max_connections} × {work_mem}) is {committed}, more than its memory ({memory}).')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
