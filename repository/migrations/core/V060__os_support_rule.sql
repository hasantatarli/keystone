/*
===============================================================================
Migration No : 060
Version      : V060
Title        : Operating System Support Rule
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds operating system releases to the release reference (Windows Server,
RHEL, Rocky Linux, AlmaLinux, Oracle Linux, CentOS, Ubuntu LTS, Debian,
SLES; taken 2026-11-11) and PG-LIFE-003 Operating System Support in
PG_LIFECYCLE_HEALTH, judged on the end of free security updates.
===============================================================================
*/


/*
Design notes (2026-11-11, Hasan)
--------------------------------
- End of support is the end of FREE security updates: Windows Server extended
  support, RHEL maintenance support, Ubuntu standard support, Debian LTS
  (community, free), SLES general support of the service pack, Rocky / Alma
  security support, Oracle Linux premier support. Paid extensions (ESU, ELS,
  Ubuntu Pro, ELTS, LTSS, Oracle Extended Support) are not assumed: a customer
  who has one can accept the finding.
- The operating system is recognised from the host snapshot (name and
  version, as collected today; no collector change): Windows by build, Linux
  by distribution name and VERSION_ID. An operating system Keystone does not
  recognise, or a release the reference does not list, is not judged.
- Its own evidence source, KEYSTONE_OS_REFERENCE, so that a newer operating
  system reference never makes a stale PostgreSQL reference look current.
  Dates are fixed: any age is accepted. Updated by migrations and reference
  files; no online source.
- Ended — CRITICAL; ends within support_warning_window (365 days) — WARNING.
===============================================================================
*/


/* ============================================================================
   OPERATING SYSTEM REFERENCE
   ============================================================================ */

-- Sources: endoflife.date (windows-server, rhel, rocky-linux, almalinux,
-- oracle-linux, ubuntu, debian, sles), wiki.rockylinux.org, blog.centos.org;
-- read 2026-11-11. major_version: the release as the host reports it.
INSERT INTO keystone.release_reference (product, major_version, latest_minor, first_release, end_of_support) VALUES
    ('Windows Server', '2025',    NULL, '2024-11-01', '2034-11-14'),
    ('Windows Server', '2022',    NULL, '2021-08-18', '2031-10-14'),
    ('Windows Server', '2019',    NULL, '2018-11-13', '2029-01-09'),
    ('Windows Server', '2016',    NULL, '2016-10-15', '2027-01-12'),
    ('Windows Server', '2012 R2', NULL, '2013-11-25', '2023-10-10'),
    ('Windows Server', '2012',    NULL, '2012-10-30', '2023-10-10'),
    ('RHEL', '10', '10.2', '2025-05-20', '2035-05-31'),
    ('RHEL', '9',  '9.8',  '2022-05-18', '2032-05-31'),
    ('RHEL', '8',  '8.10', '2019-05-07', '2029-05-31'),
    ('RHEL', '7',  '7.9',  '2014-06-10', '2024-06-30'),
    ('Rocky Linux', '10', NULL, '2025-06-11', '2035-05-31'),
    ('Rocky Linux', '9',  NULL, '2022-07-14', '2032-05-31'),
    ('Rocky Linux', '8',  NULL, '2021-05-01', '2029-05-31'),
    ('AlmaLinux', '10', NULL, '2025-05-27', '2035-05-31'),
    ('AlmaLinux', '9',  NULL, '2022-05-26', '2032-05-31'),
    ('AlmaLinux', '8',  NULL, '2021-03-30', '2029-05-31'),
    ('Oracle Linux', '10', NULL, '2025-06-26', '2035-06-30'),
    ('Oracle Linux', '9',  NULL, '2022-07-06', '2032-06-30'),
    ('Oracle Linux', '8',  NULL, '2019-07-19', '2029-07-31'),
    ('Oracle Linux', '7',  NULL, '2014-07-23', '2024-12-31'),
    ('CentOS', '8', NULL, '2019-09-24', '2021-12-31'),
    ('CentOS', '7', NULL, '2014-07-07', '2024-06-30'),
    ('Ubuntu', '26.04', NULL, '2026-04-23', '2031-05-29'),
    ('Ubuntu', '24.04', NULL, '2024-04-25', '2029-05-31'),
    ('Ubuntu', '22.04', NULL, '2022-04-21', '2027-06-01'),
    ('Ubuntu', '20.04', NULL, '2020-04-23', '2025-05-31'),
    ('Ubuntu', '18.04', NULL, '2018-04-26', '2023-05-31'),
    ('Ubuntu', '16.04', NULL, '2016-04-21', '2021-04-02'),
    ('Debian', '13', NULL, '2025-08-09', '2030-06-30'),
    ('Debian', '12', NULL, '2023-06-10', '2028-06-30'),
    ('Debian', '11', NULL, '2021-08-14', '2026-08-31'),
    ('Debian', '10', NULL, '2019-07-06', '2024-06-30'),
    ('Debian', '9',  NULL, '2017-06-17', '2022-07-01'),
    ('SLES', '16.0', NULL, '2025-11-04', '2027-11-30'),
    ('SLES', '15.7', NULL, '2025-06-17', '2031-07-31'),
    ('SLES', '15.6', NULL, '2024-06-26', '2025-12-31'),
    ('SLES', '15.5', NULL, '2023-06-20', '2024-12-31'),
    ('SLES', '15.4', NULL, '2022-06-21', '2023-12-31'),
    ('SLES', '15.3', NULL, '2021-06-22', '2022-12-31'),
    ('SLES', '12.5', NULL, '2019-12-09', '2024-10-31')
ON CONFLICT (product, major_version) DO NOTHING;

INSERT INTO keystone.release_reference_source (product, as_of, source, source_detail)
SELECT p, '2026-11-11 12:00:00+03', 'SEED', 'https://endoflife.date'
FROM unnest(ARRAY['Windows Server', 'RHEL', 'Rocky Linux', 'AlmaLinux', 'Oracle Linux',
                  'CentOS', 'Ubuntu', 'Debian', 'SLES']) AS p
ON CONFLICT (product) DO NOTHING;


/* ============================================================================
   RULE
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, 'PG-LIFE-003', 'Operating System Support',
       'Detects database servers whose operating system release is out of free security updates or soon will be.',
       'PG_HOST_SNAPSHOT', NULL,
       '{node_name} runs {os}, whose free security updates ended on {end_of_support}.',
       'Plan the move to a supported operating system release.', 'LIFECYCLE'
FROM keystone.assessment_definition ad
WHERE ad.assessment_key = 'PG_LIFECYCLE_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rule_id, 'support_warning_window', 31536000, 'SECOND',
       'An operating system release whose free security updates end within this window is reported.'
FROM keystone.rule_definition
WHERE rule_key = 'PG-LIFE-003'
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, e.evidence_source, TRUE, e.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-LIFE-003', 'PG_HOST_SNAPSHOT',      86400),
    ('PG-LIFE-003', 'KEYSTONE_OS_REFERENCE', NULL)
) AS e (rule_key, evidence_source, max_age_seconds) ON e.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES ('PG-LIFE-003', 'SECURITY'), ('PG-LIFE-003', 'AVAILABILITY')) AS c (rule_key, category_key)
    ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-LIFE-003', 'tr', 'NAME', 'İşletim sistemi desteği'),
('PG-LIFE-003', 'tr', 'HEALTHY', 'Bütün sunucuların işletim sistemi sürümü en az bir yıl daha ücretsiz güvenlik güncellemesi alıyor.'),
('PG-LIFE-003', 'tr', 'MEANING', 'Bazı veritabanı sunucularının işletim sistemi sürümü için ücretsiz güvenlik güncellemeleri bitmiş ya da yakında bitiyor.'),
('PG-LIFE-003', 'tr', 'CAUSES', E'- İşletim sistemi yükseltmesi planlanmadı ya da ertelendi\n- Sunucu taşıma (yeni sunucuya geçiş) veritabanı yükseltmesiyle birlikte düşünülmedi'),
('PG-LIFE-003', 'tr', 'IMPACT', 'Ücretsiz güvenlik güncellemesi bitmiş bir işletim sisteminde yeni bulunan açıklar kapanmaz; veritabanı ne kadar güncel olursa olsun sunucu açık kalır. Yeni PostgreSQL sürümlerinin paketleri eski işletim sistemi sürümleri için yayımlanmayabilir; bu da veritabanı yükseltmesini engeller.'),
('PG-LIFE-003', 'tr', 'RECOMMENDATION', E'- Desteklenen bir işletim sistemi sürümüne geçişi planlayın; çoğu zaman yeni sunucu kurup veritabanını taşımak yerinde yükseltmeden daha güvenlidir\n- Geçişi PostgreSQL major yükseltmesiyle birlikte planlamayı değerlendirin\n- Ücretli uzatılmış destek (Windows ESU, RHEL ELS, Ubuntu Pro, SLES LTSS gibi) alındıysa bu bulgu bilinen ve kabul edilmiş risk olarak işaretlenebilir'),
('PG-LIFE-003', 'tr', 'FINDING', '{node_name} {os} çalıştırıyor; bu sürümün ücretsiz güvenlik güncellemeleri {end_of_support} tarihinde bitti.'),
('PG-LIFE-003', 'tr', 'FINDING_ALT', '{node_name} {os} çalıştırıyor; bu sürümün ücretsiz güvenlik güncellemeleri {end_of_support} tarihinde bitiyor ({days_left} gün kaldı).'),
('PG-LIFE-003', 'en', 'NAME', 'Operating system support'),
('PG-LIFE-003', 'en', 'HEALTHY', 'The operating system release of every server gets free security updates for at least another year.'),
('PG-LIFE-003', 'en', 'MEANING', 'Free security updates for the operating system release of some database servers have ended or end soon.'),
('PG-LIFE-003', 'en', 'CAUSES', E'- The operating system upgrade was not planned or was postponed\n- Moving to a new server was not planned together with the database upgrade'),
('PG-LIFE-003', 'en', 'IMPACT', 'On an operating system without free security updates, newly found vulnerabilities stay open; the server is exposed however current the database is. Packages of new PostgreSQL versions may not be published for old operating system releases, which blocks the database upgrade.'),
('PG-LIFE-003', 'en', 'RECOMMENDATION', E'- Plan the move to a supported operating system release; building a new server and moving the database is often safer than an in-place upgrade\n- Consider planning it together with the PostgreSQL major upgrade\n- If paid extended support is in place (Windows ESU, RHEL ELS, Ubuntu Pro, SLES LTSS, say), this finding can be marked as a known and accepted risk'),
('PG-LIFE-003', 'en', 'FINDING', '{node_name} runs {os}, whose free security updates ended on {end_of_support}.'),
('PG-LIFE-003', 'en', 'FINDING_ALT', '{node_name} runs {os}, whose free security updates end on {end_of_support} (in {days_left} days).')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;


/* ============================================================================
   CONSISTENCY VIEW: REFERENCE EVIDENCE IS NOT SCHEDULED
   ============================================================================ */

-- As V059, without the operating system reference either.
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
  AND rer.evidence_source NOT IN ('KEYSTONE_RELEASE_REFERENCE', 'KEYSTONE_OS_REFERENCE')
  AND
  (
      ca.assignment_id IS NULL
      OR (rer.max_age_seconds IS NOT NULL AND ca.interval_seconds > rer.max_age_seconds)
  );
