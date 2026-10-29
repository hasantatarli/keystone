/*
===============================================================================
Migration No : 043
Version      : V043
Title        : PUBLIC Create Cause Wording

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
PG-SEC-004 CAUSES: the pre-15 default is a possible cause, not a fact about
the database (Hasan, lab review 2026-10-27).
===============================================================================
*/

UPDATE keystone.rule_text t
SET text = v.text
FROM keystone.rule_definition rd,
     (VALUES
        ('tr', E'- Veritabanı PostgreSQL 15 öncesinde oluşturulmuş olabilir; PostgreSQL 15 öncesinde public schema''da herkese CREATE yetkisi varsayılan olarak veriliyordu ve bu yetki upgrade ile korunur\n- Yetki bilerek ya da kolaylık için herkese verildi'),
        ('en', E'- The database may have been created before PostgreSQL 15; before PostgreSQL 15 everyone got CREATE on schema public by default, and upgrades keep it\n- The privilege was granted to everyone on purpose or for convenience')
     ) AS v (language_code, text)
WHERE rd.rule_key = 'PG-SEC-004'
  AND t.rule_id = rd.rule_id
  AND t.language_code = v.language_code
  AND t.text_type = 'CAUSES';
