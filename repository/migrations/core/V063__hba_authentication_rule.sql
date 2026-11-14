/*
===============================================================================
Migration No : 063
Version      : V063

Title        : Client Authentication Rule
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-SEC-005 Weak Client Authentication (PG_SECURITY_HEALTH) on the new
collector PG_HBA_RULES (provider migration PG026): pg_hba.conf lines that
let clients in with trust, send passwords in clear text, or use md5.
===============================================================================
*/


/*
Design notes (2026-11-14, Hasan)
--------------------------------
- trust over the network: CRITICAL (no password at all); trust on the local
  socket: WARNING (any operating system user, as any database user, postgres
  included); password over the network: WARNING (clear text); md5: INFO
  (deprecated in PostgreSQL 18, weaker than scram-sha-256).
- pg_hba_file_rules is superuser only by default. Without the privilege the
  node is not assessed and the report gives the two GRANT statements, as
  decided for sequences (PG-CAP-002): a missing privilege is said, not
  guessed around. Offline collection as postgres reads it.
- Every node: pg_hba.conf is per server and a replica becomes primary.
- Texts: IMPACT says what happens now and if it goes on; RECOMMENDATION ends
  with what the fix costs.
===============================================================================
*/


INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, 'PG-SEC-005', 'Weak Client Authentication',
       'Detects pg_hba.conf lines that accept clients with trust, clear-text password or md5.',
       'PG_HBA_RULES', NULL,
       '{node_name}: pg_hba.conf line {line_number} ({conn_type} {databases} {users} {address}) uses {auth_method}.',
       'Use scram-sha-256 for network connections and peer for local ones.', 'SECURITY'
FROM keystone.assessment_definition ad
WHERE ad.assessment_key = 'PG_SECURITY_HEALTH'
ON CONFLICT (rule_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rule_id, 'PG_HBA_RULES', TRUE, 86400
FROM keystone.rule_definition WHERE rule_key = 'PG-SEC-005'
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rule_id, 'SECURITY'
FROM keystone.rule_definition WHERE rule_key = 'PG-SEC-005'
ON CONFLICT (rule_id, category_key) DO NOTHING;

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
('PG-SEC-005', 'tr', 'NAME', 'Zayıf istemci kimlik doğrulaması'),
('PG-SEC-005', 'tr', 'HEALTHY', 'pg_hba.conf''ta trust, şifresiz (password) ya da md5 kullanan kural yok.'),
('PG-SEC-005', 'tr', 'MEANING', 'pg_hba.conf''taki bazı satırlar istemcileri zayıf yöntemlerle içeri alıyor: trust şifre sormaz (ağdan kritik, yerel socket''te uyarı), password şifreyi ağda açık metin gönderir (uyarı), md5 PostgreSQL 18''de kullanımdan kalkıyor ve scram-sha-256''dan zayıf (bilgi).'),
('PG-SEC-005', 'tr', 'CAUSES', E'- Kurulumda ya da test sırasında kolaylık için trust bırakılmış\n- Bir uygulamanın bağlanamaması geçici olarak trust ile çözülmüş ve geri alınmamış\n- Eski sürümlerden kalma md5 ayarları scram''a taşınmamış'),
('PG-SEC-005', 'tr', 'IMPACT', E'Şimdi: trust satırının kapsadığı adreslerden ve kullanıcılarla şifre sorulmadan bağlanılabiliyor (yerel socket''te sunucudaki her işletim sistemi kullanıcısı, postgres dahil her veritabanı kullanıcısı olabilir); password satırlarında şifre ağı dinleyen birine görünür.\nBöyle devam ederse: ağdaki tek bir ele geçirilmiş makine ya da sunucuda yetkisiz bir işletim sistemi kullanıcısı, superuser dahil herhangi bir veritabanı kullanıcısı olarak bağlanıp veriyi okuyabilir, değiştirebilir ya da silebilir.'),
('PG-SEC-005', 'tr', 'RECOMMENDATION', E'- Ağ satırlarında trust ve password yerine scram-sha-256 kullanın; adresleri gereken en dar aralıkla sınırlayın (0.0.0.0/0 yerine uygulama sunucularının adresleri)\n- Yerel satırlarda trust yerine peer kullanın (işletim sistemi kullanıcısı veritabanı kullanıcısıyla eşleşir)\n- md5''ten scram-sha-256''ya geçerken önce password_encryption = scram-sha-256 yapın, kullanıcıların şifrelerini yeniden atayın (ALTER ROLE ... PASSWORD), sonra pg_hba''da md5''i scram-sha-256 yapın\n- Değişiklikten sonra: SELECT pg_reload_conf(); ve hatalı satır olmadığını pg_hba_file_rules''taki error kolonundan kontrol edin\n- Bedeli: pg_hba değişikliği yalnızca reload ister; trust''a güvenen uygulama ya da betiklere şifre tanımlamak gerekir. md5''ten geçişte şifrelerin yeniden atanması uygulamalarla birlikte planlanmalıdır.'),
('PG-SEC-005', 'tr', 'FINDING', '{node_name}: pg_hba.conf satır {line_number} ({conn_type} {databases} {users} {address}) {auth_method} kullanıyor.'),
('PG-SEC-005', 'en', 'NAME', 'Weak client authentication'),
('PG-SEC-005', 'en', 'HEALTHY', 'No pg_hba.conf rule uses trust, clear-text password or md5.'),
('PG-SEC-005', 'en', 'MEANING', 'Some pg_hba.conf lines let clients in with weak methods: trust asks no password (critical over the network, warning on the local socket), password sends it in clear text over the network (warning), md5 is deprecated in PostgreSQL 18 and weaker than scram-sha-256 (info).'),
('PG-SEC-005', 'en', 'CAUSES', E'- trust was left from installation or testing for convenience\n- An application that could not connect was fixed with trust and never reverted\n- md5 settings from older versions were not moved to scram'),
('PG-SEC-005', 'en', 'IMPACT', E'Now: from the addresses and as the users a trust line covers, connections need no password (on the local socket any operating system user on the server can be any database user, postgres included); on password lines the password is visible to anyone listening on the network.\nIf it goes on: a single compromised machine on the network, or an unauthorized operating system user on the server, can connect as any database user, superuser included, and read, change or delete data.'),
('PG-SEC-005', 'en', 'RECOMMENDATION', E'- On network lines use scram-sha-256 instead of trust and password; narrow the addresses to what is needed (the application servers instead of 0.0.0.0/0)\n- On local lines use peer instead of trust (the operating system user must match the database user)\n- Moving from md5 to scram-sha-256: first password_encryption = scram-sha-256, set the users'' passwords again (ALTER ROLE ... PASSWORD), then change md5 to scram-sha-256 in pg_hba\n- After the change: SELECT pg_reload_conf(); and check the error column of pg_hba_file_rules\n- Cost: a pg_hba change needs only a reload; applications or scripts relying on trust need a password. Re-setting passwords for md5 must be planned with the applications.'),
('PG-SEC-005', 'en', 'FINDING', '{node_name}: pg_hba.conf line {line_number} ({conn_type} {databases} {users} {address}) uses {auth_method}.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
