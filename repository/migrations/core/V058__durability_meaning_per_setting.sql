/*
===============================================================================
Migration No : 058
Version      : V058
Title        : Durability Meaning Per Setting

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
PG-CONF-002 says which risk the setting carries: fsync or full_page_writes off
can corrupt the database in a crash; synchronous_commit off cannot, it can
lose the last commits. Review of the first pilot report (2026-11-11): one
sentence for all three overstated synchronous_commit.
===============================================================================
*/

UPDATE keystone.rule_text rt
SET text = t.text
FROM keystone.rule_definition rd
JOIN (VALUES
    ('tr', 'MEANING', 'Çökme anındaki veri güvenliğini etkileyen bir ayar kapatılmış. Riskleri aynı değildir: fsync ya da full_page_writes kapalıysa bir çökme veritabanını bozabilir; synchronous_commit kapalıysa veritabanı bozulmaz, yalnızca son commit''ler kaybolabilir.'),
    ('en', 'MEANING', 'A setting that affects data safety in a crash is turned off. The risks differ: with fsync or full_page_writes off a crash can corrupt the database; with synchronous_commit off it is not corrupted, only the last commits can be lost.'),
    ('tr', 'RECOMMENDATION', E'- fsync ve full_page_writes kapalıysa hemen açın\n- synchronous_commit kapalıysa bunun bilinçli bir karar olup olmadığını ve uygulamanın kabul ettiği veri kaybı penceresini (son kaç saniyelik commit''ler) sahibiyle netleştirin ve belgeleyin\n- Kritik işlemler (finansal kayıtlar gibi) varsa synchronous_commit''i yalnızca kayıp kabul edilebilen kullanıcı ya da işlemler için kapatın'),
    ('en', 'RECOMMENDATION', E'- If fsync or full_page_writes is off, turn it on immediately\n- If synchronous_commit is off, settle with the owner whether this is a conscious decision and which data-loss window (the commits of the last seconds) the application accepts, and document it\n- With critical transactions (financial records, say), turn synchronous_commit off only for the users or transactions where a loss is acceptable')
) AS t (language_code, text_type, text) ON TRUE
WHERE rd.rule_key = 'PG-CONF-002'
  AND rt.rule_id = rd.rule_id
  AND rt.language_code = t.language_code
  AND rt.text_type = t.text_type;
