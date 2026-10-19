/*
===============================================================================
Migration No : 030
Version      : V030
Title        : Scoped Healthy Texts and Thresholds Used

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Rewrites the HEALTHY rule texts so they claim only what the rule checked,
with {warning}/{critical} filled from the thresholds actually used; stores
those thresholds in assessment_result.thresholds_used; removes the generic
topic healthy text (topic summaries are built from the rule texts).
===============================================================================
*/


/*
Design notes (2026-10-19, review of the first lab report)
---------------------------------------------------------
"No long transaction is open" next to a 29-minute idle transaction was true
for the rule (threshold 30 minutes) but false as a sentence. A healthy text
states the check and its limit, nothing more. Limits come from the
thresholds used at evaluation time, so texts and results cannot disagree,
and an old report keeps the limits it was produced with after the
Dictionary changes.

What a rule does not evaluate is not listed in reports; it is documented in
the Rule Catalog (known limitations) and is input for new rules.
===============================================================================
*/

ALTER TABLE keystone.assessment_result
    ADD COLUMN thresholds_used JSONB;

COMMENT ON COLUMN keystone.assessment_result.thresholds_used IS
'Thresholds applied when the rule was evaluated: [{"severity", "value", "unit"}]. NULL for rules without thresholds and results before V030.';


ALTER TABLE keystone.dictionary_topic_text
    DROP COLUMN healthy_text;


UPDATE keystone.rule_text rt
SET text = t.text
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-001', 'tr', 'Boşta bekleme süresi {warning} sınırını aşan transaction yok.'),
    ('PG-TRAN-001', 'en', 'No transaction has been idle longer than the {warning} limit.'),
    ('PG-TRAN-003', 'tr', 'Açık kalma süresi {warning} sınırını aşan transaction yok.'),
    ('PG-TRAN-003', 'en', 'No transaction has been open longer than the {warning} limit.'),
    ('PG-TRAN-002', 'tr', 'Hiçbir veritabanında transaction ID yaşı {warning} sınırına ulaşmamış.'),
    ('PG-TRAN-002', 'en', 'No database has reached a transaction ID age of {warning}.'),
    ('PG-REP-001',  'tr', 'Hiçbir replication slot''un WAL''ı normal sınırı (max_wal_size) aşmamış.'),
    ('PG-REP-001',  'en', 'No replication slot retains WAL beyond the normal limit (max_wal_size).'),
    ('PG-REP-002',  'tr', 'WAL''ı korunmayan ya da silinmiş replication slot yok.'),
    ('PG-REP-002',  'en', 'No replication slot has unprotected or removed WAL.'),
    ('PG-CONN-001', 'tr', 'Hata alıp rollback edilmemiş transaction''da bekleyen session yok.'),
    ('PG-CONN-001', 'en', 'No session is waiting in a failed transaction that was not rolled back.')
) AS t (rule_key, language_code, text) ON t.rule_key = rd.rule_key
WHERE rt.rule_id = rd.rule_id
  AND rt.language_code = t.language_code
  AND rt.text_type = 'HEALTHY';
