/*
===============================================================================
Migration No : 037
Version      : V037
Title        : Durability Rule Wording

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
PG-CONF-002 keeps the technical term "durability" in Turkish instead of
translating it ("dayanıklılık"), which made the rule harder to understand.
===============================================================================
*/

UPDATE keystone.rule_text rt
SET text = t.text
FROM keystone.rule_definition rd
JOIN (VALUES
    ('tr', 'NAME',    'Durability''yi zayıflatan ayarlar'),
    ('tr', 'MEANING', 'Çökme anında verinin korunmasını (durability) sağlayan bir ayar, performans için kapatılmış.'),
    ('en', 'MEANING', 'A setting that protects data in a crash (durability) has been turned off for performance.')
) AS t (language_code, text_type, text) ON TRUE
WHERE rd.rule_key = 'PG-CONF-002'
  AND rt.rule_id = rd.rule_id
  AND rt.language_code = t.language_code
  AND rt.text_type = t.text_type;
