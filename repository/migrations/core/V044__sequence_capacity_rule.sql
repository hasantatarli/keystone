/*
===============================================================================
Migration No : 044
Version      : V044
Title        : Sequence Capacity Rule

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-CAP-002 Sequence Exhaustion to PG_CAPACITY_HEALTH on the new collector
PG_SEQUENCE_CAPACITY (PG018), and renames topic STORAGE to "Storage and
capacity".
===============================================================================
*/


/*
Design notes (2026-10-26/29, Hasan)
-----------------------------------
- Usage = last value / limit; the limit is the smaller of the sequence's own
  maximum and the maximum of the column it feeds (a bigint sequence feeding an
  integer column runs out at 2,147,483,647). WARNING 75 %, CRITICAL 90 %:
  changing the column to bigint rewrites the table and needs planned downtime.
- Reading a sequence's value needs SELECT or USAGE on it; pg_monitor is not
  enough. SELECT on a sequence exposes only its counter, not table data.
  Without it the rule ends INSUFFICIENT_EVIDENCE and names the privilege; with
  partial privilege the readable sequences are judged and the rule is never
  called healthy while some could not be read.
- Cycling sequences wrap around on purpose and are not judged. Keys generated
  by the application (max(id) + 1) are out of scope.
===============================================================================
*/

UPDATE keystone.dictionary_topic_text SET name = v.name
FROM (VALUES ('tr', 'Depolama ve kapasite'), ('en', 'Storage and capacity')) AS v (language_code, name)
WHERE dictionary_topic_text.topic_key = 'STORAGE'
  AND dictionary_topic_text.language_code = v.language_code;

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, 'PG-CAP-002', 'Sequence Exhaustion',
       'Detects sequences close to the limit of their own type or of the column they feed.',
       'PG_SEQUENCE_CAPACITY', NULL,
       'Sequence {sequence} ({column}) has used {percent}% of its limit ({last_value} of {limit}).',
       'Plan the change of the column and the sequence to bigint before the limit is reached; it rewrites the table.',
       'STORAGE'
FROM keystone.assessment_definition ad
WHERE ad.assessment_key = 'PG_CAPACITY_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, 'PERCENT'
FROM keystone.rule_definition rd
CROSS JOIN (VALUES ('WARNING', 75), ('CRITICAL', 90)) AS t (severity, threshold_value)
WHERE rd.rule_key = 'PG-CAP-002'
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rule_id, 'PG_SEQUENCE_CAPACITY', TRUE, 86400
FROM keystone.rule_definition WHERE rule_key = 'PG-CAP-002'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
CROSS JOIN (VALUES ('AVAILABILITY'), ('CAPACITY')) AS c (category_key)
WHERE rd.rule_key = 'PG-CAP-002'
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-CAP-002', 'tr', 'NAME', 'Sequence tükenmesi'),
('PG-CAP-002', 'tr', 'HEALTHY', 'Hiçbir sequence sınırının {warning} kadarına ulaşmamış.'),
('PG-CAP-002', 'tr', 'MEANING', 'Bazı tablolarda otomatik artan ID''leri üreten sequence''ler, kendi tiplerinin ya da besledikleri kolonun alabileceği en büyük değere yaklaşmış.'),
('PG-CAP-002', 'tr', 'CAUSES', E'- Tablo integer (int4) ya da smallint bir ID kolonuyla tasarlandı ve kayıt sayısı beklenenden fazla büyüdü\n- Sequence büyük adımlarla artıyor ya da başarısız insert''ler sayıları boşa harcıyor\n- bigint bir sequence, integer bir kolonu besliyor'),
('PG-CAP-002', 'tr', 'IMPACT', 'Sınıra gelindiğinde o tabloya yapılan her INSERT hata verir ve uygulama yeni kayıt ekleyemez. Kolonu bigint yapmak tabloyu baştan yazar; büyük tablolarda saatler süren bir lock ve planlı bakım gerektirir.'),
('PG-CAP-002', 'tr', 'RECOMMENDATION', E'- Kolonu ve sequence''i bigint yapmak için bir bakım penceresi planlayın; büyük tablolarda bunu sınıra aylar kala yapın\n- Kesinti kaldırılamıyorsa yeni bir bigint kolonla kademeli geçiş planlayın\n- Geçici bir çözüm olarak sequence''i negatif değerlerden başlatmak mümkün, ama uygulamanın negatif ID''yi kabul ettiğini doğrulayın'),
('PG-CAP-002', 'tr', 'FINDING', '{sequence} sequence''i ({column}) sınırının %{percent} kadarını kullanmış ({last_value} / {limit}).'),
('PG-CAP-002', 'en', 'NAME', 'Sequence exhaustion'),
('PG-CAP-002', 'en', 'HEALTHY', 'No sequence has reached {warning} of its limit.'),
('PG-CAP-002', 'en', 'MEANING', 'Sequences that generate auto-increment IDs are close to the largest value of their own type or of the column they feed.'),
('PG-CAP-002', 'en', 'CAUSES', E'- The table was designed with an integer (int4) or smallint ID column and grew more than expected\n- The sequence increments in large steps or failed inserts waste numbers\n- A bigint sequence feeds an integer column'),
('PG-CAP-002', 'en', 'IMPACT', 'At the limit every INSERT into the table fails and the application cannot add rows. Changing the column to bigint rewrites the table; on large tables that means a lock for hours and planned maintenance.'),
('PG-CAP-002', 'en', 'RECOMMENDATION', E'- Plan a maintenance window to change the column and the sequence to bigint; for large tables do it months before the limit\n- If downtime is not possible, plan a gradual move to a new bigint column\n- As a stopgap the sequence can restart from negative values, but check that the application accepts negative IDs'),
('PG-CAP-002', 'en', 'FINDING', 'Sequence {sequence} ({column}) has used {percent}% of its limit ({last_value} of {limit}).')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
