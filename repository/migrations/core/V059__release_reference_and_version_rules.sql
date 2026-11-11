/*
===============================================================================
Migration No : 059
Version      : V059
Title        : Release Reference and Version Rules

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the release reference (major versions with first release, end of
support and latest minor, and where and when it was taken) seeded from
postgresql.org on 2026-11-11, and PG-LIFE-001 Minor Version Behind and
PG-LIFE-002 Major Version Support in PG_LIFECYCLE_HEALTH. The reference is
refreshed online or from a reference file, not by migrations only.
===============================================================================
*/


/*
Design notes (2026-11-11, Hasan)
--------------------------------
A version finding is only worth giving when the reference is right (Hasan:
"two years later still the old versions: no point"). Hence:
- The reference is reference data, not Dictionary: Keystone refreshes it when
  its own machine reaches the internet (postgresql.org, then endoflife.date),
  or imports a reference file (a quarterly package for installations without
  internet); this migration's seed is the fallback.
- End-of-support dates are fixed by the versioning policy (five years) and do
  not go stale: PG-LIFE-002 accepts the reference at any age; a major the
  reference does not list is not judged.
- Latest minors change every quarter: PG-LIFE-001 accepts a reference of at
  most 100 days, otherwise it is not assessed ("reference is old"), never
  reported current on stale data.
- PG-LIFE-001: behind the latest minor of its major — WARNING; 4 or more
  releases behind (about a year of fixes) — CRITICAL. PG-LIFE-002: support
  ended — CRITICAL; ends within support_warning_window (365 days) — WARNING.
===============================================================================
*/


/* ============================================================================
   RELEASE REFERENCE
   ============================================================================ */

CREATE TABLE keystone.release_reference
(
    product          VARCHAR(50)  NOT NULL,          -- 'PostgreSQL'
    major_version    VARCHAR(10)  NOT NULL,          -- '17', '9.6'
    latest_minor     VARCHAR(20),                    -- '17.11'
    first_release    DATE,
    end_of_support   DATE,

    CONSTRAINT pk_release_reference PRIMARY KEY (product, major_version)
);

CREATE TABLE keystone.release_reference_source
(
    product      VARCHAR(50)  NOT NULL,
    as_of        TIMESTAMPTZ  NOT NULL,              -- when the reference was taken
    source       VARCHAR(20)  NOT NULL,              -- SEED | FILE | ONLINE
    source_detail TEXT,                              -- URL or file name

    CONSTRAINT pk_release_reference_source PRIMARY KEY (product),
    CONSTRAINT ck_release_reference_source CHECK (source IN ('SEED', 'FILE', 'ONLINE'))
);

COMMENT ON TABLE keystone.release_reference IS
'Reference data, not Dictionary: refreshed online or from a reference file (repository.lifecycle.release_reference).';

INSERT INTO keystone.release_reference (product, major_version, latest_minor, first_release, end_of_support) VALUES
    ('PostgreSQL', '18',  '18.6',   '2025-09-25', '2030-11-14'),
    ('PostgreSQL', '17',  '17.11',  '2024-09-26', '2029-11-08'),
    ('PostgreSQL', '16',  '16.15',  '2023-09-14', '2028-11-09'),
    ('PostgreSQL', '15',  '15.19',  '2022-10-13', '2027-11-11'),
    ('PostgreSQL', '14',  '14.24',  '2021-09-30', '2026-11-12'),
    ('PostgreSQL', '13',  '13.23',  '2020-09-24', '2025-11-13'),
    ('PostgreSQL', '12',  '12.22',  '2019-10-03', '2024-11-21'),
    ('PostgreSQL', '11',  '11.22',  '2018-10-18', '2023-11-09'),
    ('PostgreSQL', '10',  '10.23',  '2017-10-05', '2022-11-10'),
    ('PostgreSQL', '9.6', '9.6.24', '2016-09-29', '2021-11-11'),
    ('PostgreSQL', '9.5', '9.5.25', '2016-01-07', '2021-02-11'),
    ('PostgreSQL', '9.4', '9.4.26', '2014-12-18', '2020-02-13')
ON CONFLICT (product, major_version) DO NOTHING;

INSERT INTO keystone.release_reference_source (product, as_of, source, source_detail) VALUES
    ('PostgreSQL', '2026-11-11 12:00:00+03', 'SEED', 'https://www.postgresql.org/support/versioning')
ON CONFLICT (product) DO NOTHING;


/* ============================================================================
   RULES
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, x.evidence_source,
       r.default_severity, r.finding_template, r.recommendation, x.topic_key
FROM (VALUES
    ('PG-LIFE-001', 'Minor Version Behind',
     'Detects servers behind the latest minor release of their major version.',
     NULL,
     '{node_name} runs PostgreSQL {version}; the latest {major} release is {latest} ({behind} releases behind).',
     'Plan a minor update; it changes no data format and needs only a restart.'),
    ('PG-LIFE-002', 'Major Version Support',
     'Detects major versions whose community support has ended or ends soon.',
     NULL,
     '{node_name} runs PostgreSQL {major}, whose community support ended on {end_of_support}.',
     'Plan the upgrade to a supported major version (pg_upgrade or logical replication).')
) AS r (rule_key, name, description, default_severity, finding_template, recommendation)
JOIN keystone.assessment_definition ad ON ad.assessment_key = 'PG_LIFECYCLE_HEALTH'
CROSS JOIN (VALUES ('PG_INSTANCE_INVENTORY', 'LIFECYCLE')) AS x (evidence_source, topic_key)
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rule_id, t.severity, t.threshold_value, 'RELEASE'
FROM keystone.rule_definition
CROSS JOIN (VALUES ('WARNING', 1), ('CRITICAL', 4)) AS t (severity, threshold_value)
WHERE rule_key = 'PG-LIFE-001'
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rule_id, 'support_warning_window', 31536000, 'SECOND',
       'A major version whose support ends within this window is reported.'
FROM keystone.rule_definition
WHERE rule_key = 'PG-LIFE-002'
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

-- The reference is evidence whose age is its as_of: 100 days for minors, any age for end-of-support dates.
INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, e.evidence_source, TRUE, e.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-LIFE-001', 'PG_INSTANCE_INVENTORY',      3600),
    ('PG-LIFE-001', 'KEYSTONE_RELEASE_REFERENCE', 8640000),
    ('PG-LIFE-002', 'PG_INSTANCE_INVENTORY',      3600),
    ('PG-LIFE-002', 'KEYSTONE_RELEASE_REFERENCE', NULL)
) AS e (rule_key, evidence_source, max_age_seconds) ON e.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-LIFE-001', 'SECURITY'),
    ('PG-LIFE-001', 'AVAILABILITY'),
    ('PG-LIFE-002', 'SECURITY'),
    ('PG-LIFE-002', 'AVAILABILITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
-- PG-LIFE-001 ---------------------------------------------------------------
('PG-LIFE-001', 'tr', 'NAME', 'Geride kalan minor sürüm'),
('PG-LIFE-001', 'tr', 'HEALTHY', 'Bütün sunucular Keystone''un sürüm referansındaki en son minor sürümde.'),
('PG-LIFE-001', 'tr', 'MEANING', 'Bazı sunucular kendi major sürümlerinin en son minor sürümünde değil; yayımlanmış hata ve güvenlik düzeltmeleri uygulanmamış.'),
('PG-LIFE-001', 'tr', 'CAUSES', E'- Minor güncellemeler düzenli bakım takvimine alınmamış\n- Restart için kesinti penceresi bulunamadı\n- Paket deposu sunucuda güncellenmiyor'),
('PG-LIFE-001', 'tr', 'IMPACT', 'Minor sürümler yalnızca hata ve güvenlik düzeltmesi içerir; uygulanmayan düzeltmeler bilinen hataların ve güvenlik açıklarının sistemde kalması demektir. Veri biçimi değişmediği için güncelleme yalnızca bir restart gerektirir.'),
('PG-LIFE-001', 'tr', 'RECOMMENDATION', E'- Aradaki sürümlerin sürüm notlarını okuyun; bazı sürümler güncellemeden sonra ek adım (örneğin bir index''in yeniden oluşturulması) ister\n- Minor güncellemeyi bakım takvimine alın; replikasyonlu sistemlerde önce replica''ları güncelleyin, sonra switchover yapın\n- Minor güncellemeleri üç ayda bir yapılan düzenli bir iş haline getirin'),
('PG-LIFE-001', 'tr', 'FINDING', '{node_name} PostgreSQL {version} çalıştırıyor; {major} için en son sürüm {latest} ({behind} sürüm geride).'),
('PG-LIFE-001', 'en', 'NAME', 'Minor version behind'),
('PG-LIFE-001', 'en', 'HEALTHY', 'Every server runs the latest minor release in Keystone''s release reference.'),
('PG-LIFE-001', 'en', 'MEANING', 'Some servers do not run the latest minor release of their major version; published bug and security fixes are not applied.'),
('PG-LIFE-001', 'en', 'CAUSES', E'- Minor updates are not part of a regular maintenance schedule\n- No downtime window for the restart was found\n- The package repository is not updated on the server'),
('PG-LIFE-001', 'en', 'IMPACT', 'Minor releases contain only bug and security fixes; fixes not applied mean known bugs and vulnerabilities stay in the system. The data format does not change, so the update needs only a restart.'),
('PG-LIFE-001', 'en', 'RECOMMENDATION', E'- Read the release notes of the releases in between; some ask for an extra step after the update (rebuilding an index, say)\n- Schedule the minor update; with replication update the replicas first, then switch over\n- Make minor updates a regular quarterly task'),
('PG-LIFE-001', 'en', 'FINDING', '{node_name} runs PostgreSQL {version}; the latest {major} release is {latest} ({behind} releases behind).'),
-- PG-LIFE-002 ---------------------------------------------------------------
('PG-LIFE-002', 'tr', 'NAME', 'Major sürüm desteği'),
('PG-LIFE-002', 'tr', 'HEALTHY', 'Bütün sunucuların PostgreSQL major sürümü en az bir yıl daha destekleniyor.'),
('PG-LIFE-002', 'tr', 'MEANING', 'Bazı sunucuların PostgreSQL major sürümünün topluluk desteği bitmiş ya da yakında bitiyor.'),
('PG-LIFE-002', 'tr', 'CAUSES', E'- Major sürüm yükseltmesi planlanmadı ya da ertelendi\n- Uygulamanın yeni sürümle uyumluluğu test edilmedi'),
('PG-LIFE-002', 'tr', 'IMPACT', 'Desteği biten sürüme artık hata ve güvenlik düzeltmesi yayımlanmaz; yeni bulunan açıklar kapanmaz. Uyumluluk gerektiren denetimlerde desteklenmeyen yazılım bulgu olarak sayılır. Major yükseltme hazırlık ve test gerektirdiği için erken planlanmalıdır.'),
('PG-LIFE-002', 'tr', 'RECOMMENDATION', E'- Hedef sürümü seçin ve uygulamayı bu sürümle test edin\n- Yükseltme yöntemini belirleyin: pg_upgrade (kısa kesinti) ya da logical replication (kesintiye yakın)\n- Extension''ların hedef sürümde desteklendiğini kontrol edin\n- Yükseltmeyi destek bitmeden tamamlayacak bir takvim yapın'),
('PG-LIFE-002', 'tr', 'FINDING', '{node_name} PostgreSQL {major} çalıştırıyor; bu sürümün topluluk desteği {end_of_support} tarihinde bitti.'),
('PG-LIFE-002', 'tr', 'FINDING_ALT', '{node_name} PostgreSQL {major} çalıştırıyor; bu sürümün topluluk desteği {end_of_support} tarihinde bitiyor ({days_left} gün kaldı).'),
('PG-LIFE-002', 'en', 'NAME', 'Major version support'),
('PG-LIFE-002', 'en', 'HEALTHY', 'The major version of every server is supported for at least another year.'),
('PG-LIFE-002', 'en', 'MEANING', 'The community support of some servers'' PostgreSQL major version has ended or ends soon.'),
('PG-LIFE-002', 'en', 'CAUSES', E'- The major upgrade was not planned or was postponed\n- The application was not tested with a newer version'),
('PG-LIFE-002', 'en', 'IMPACT', 'A version out of support gets no more bug or security fixes; newly found vulnerabilities stay open. Audits that require supported software count it as a finding. A major upgrade needs preparation and testing, so it should be planned early.'),
('PG-LIFE-002', 'en', 'RECOMMENDATION', E'- Choose the target version and test the application with it\n- Decide the method: pg_upgrade (short downtime) or logical replication (near zero downtime)\n- Check that the extensions are supported on the target version\n- Plan the upgrade to finish before support ends'),
('PG-LIFE-002', 'en', 'FINDING', '{node_name} runs PostgreSQL {major}, whose community support ended on {end_of_support}.'),
('PG-LIFE-002', 'en', 'FINDING_ALT', '{node_name} runs PostgreSQL {major}, whose community support ends on {end_of_support} (in {days_left} days).')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;


/* ============================================================================
   CONSISTENCY VIEW: REFERENCE EVIDENCE IS NOT SCHEDULED
   ============================================================================ */

-- As V032, without the release reference: no collector schedules it.
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
  -- Reference evidence is held by Keystone, not collected (ADR-0019).
  AND rer.evidence_source <> 'KEYSTONE_RELEASE_REFERENCE'
  AND
  (
      ca.assignment_id IS NULL
      OR (rer.max_age_seconds IS NOT NULL AND ca.interval_seconds > rer.max_age_seconds)
  );
