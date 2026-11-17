/*
===============================================================================
Migration No : 067
Version      : V067

Title        : Management Decisions
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the rule texts DECISION and DECISION_OWNER (ADR-0021): for findings a
manager has to decide on, the decision in one sentence and who takes it.
The Executive Summary lists them under "Decisions expected from you" when
the rule has a finding.
===============================================================================
*/


/*
Design notes (2026-11-17, Hasan)
--------------------------------
- Only where the fix is not the DBA's own work: it needs a business answer,
  a budget, a certificate or a maintenance window. PUBLIC schema, md5 or the
  diagnostic settings are the DBA's work and carry no decision.
- WAL archiving is a joint decision of the business unit and IT: how much
  loss is acceptable depends on whether the data can be produced again.
  Archiving is per server (cluster), never per database: it covers every
  database on it.
- The decision is a question to answer, never an invented owner, date or
  cost; the owner is a role (business unit, IT), not a person.
===============================================================================
*/


ALTER TABLE keystone.rule_text DROP CONSTRAINT ck_rule_text_type;

ALTER TABLE keystone.rule_text
    ADD CONSTRAINT ck_rule_text_type
    CHECK (text_type IN ('NAME', 'HEALTHY', 'MEANING', 'CAUSES', 'IMPACT', 'RECOMMENDATION',
                         'FINDING', 'FINDING_ALT', 'DECISION', 'DECISION_OWNER'));


INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-BKP-002', 'tr', 'DECISION_OWNER', 'İş birimi ve IT'),
('PG-BKP-002', 'tr', 'DECISION', 'Veri kaybolursa ne kadarlık kayıp kabul edilebilir, veri yeniden oluşturulabilir mi? Kabul edilemiyorsa WAL arşivleme (point-in-time recovery) planlanmalı. Arşivleme sunucu düzeyindedir; bu sunucudaki bütün veritabanlarını kapsar.'),
('PG-BKP-002', 'en', 'DECISION_OWNER', 'Business unit and IT'),
('PG-BKP-002', 'en', 'DECISION', 'If data is lost, how much loss is acceptable, and can the data be produced again? If not acceptable, WAL archiving (point-in-time recovery) should be planned. Archiving is per server; it covers every database on it.'),

('PG-SEC-003', 'tr', 'DECISION_OWNER', 'IT (güvenlik ekibiyle)'),
('PG-SEC-003', 'tr', 'DECISION', 'Veritabanı bağlantıları şifrelenmeli mi? Gerekiyorsa sertifika temin edilmeli ve restart için bakım penceresi ayrılmalı.'),
('PG-SEC-003', 'en', 'DECISION_OWNER', 'IT (with the security team)'),
('PG-SEC-003', 'en', 'DECISION', 'Should database connections be encrypted? If so, a certificate is needed and a maintenance window for the restart.'),

('PG-LIFE-001', 'tr', 'DECISION_OWNER', 'IT'),
('PG-LIFE-001', 'tr', 'DECISION', 'Minor sürüm güncellemesi için bakım penceresi ayrılmalı; düzenli (örneğin üç ayda bir) güncelleme takvime alınmalı.'),
('PG-LIFE-001', 'en', 'DECISION_OWNER', 'IT'),
('PG-LIFE-001', 'en', 'DECISION', 'A maintenance window is needed for the minor update; regular updates (every quarter, say) should be scheduled.'),

('PG-LIFE-002', 'tr', 'DECISION_OWNER', 'IT'),
('PG-LIFE-002', 'tr', 'DECISION', 'Desteği biten ya da bitmek üzere olan major sürümden yükseltme bir proje olarak planlanmalı (uygulamaların testi dahil).'),
('PG-LIFE-002', 'en', 'DECISION_OWNER', 'IT'),
('PG-LIFE-002', 'en', 'DECISION', 'Upgrading from a major version whose support ends should be planned as a project (applications tested included).'),

('PG-LIFE-003', 'tr', 'DECISION_OWNER', 'IT'),
('PG-LIFE-003', 'tr', 'DECISION', 'Desteği biten ya da bitmek üzere olan işletim sisteminin yükseltilmesi ya da sunucunun taşınması planlanmalı.'),
('PG-LIFE-003', 'en', 'DECISION_OWNER', 'IT'),
('PG-LIFE-003', 'en', 'DECISION', 'Upgrading the operating system whose support ends, or moving the server, should be planned.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
