/*
===============================================================================
Migration No : 068
Version      : V068
Title        : HBA Open Address

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
PG-SEC-005: a weak pg_hba.conf line open to every address (all, 0.0.0.0/0,
::/0) is one level higher (md5 INFO to WARNING, password WARNING to
CRITICAL). The texts no longer list methods the system may not have: each
line's reason is in the finding table (Why column).
===============================================================================
*/


/*
Design notes (2026-11-18, Hasan)
--------------------------------
- laptop-pg (hc140): host all all 0.0.0.0/0 md5 was INFO although every
  database and user could be tried from any network.
- The address decides, not all databases / all users: one measure, easy to
  explain.
- scram-sha-256 open to every address is network exposure, not weak
  authentication: not a finding of this rule (a firewall matter).
- The severity change is in the evaluator; texts only here.
===============================================================================
*/


UPDATE keystone.rule_text rt
SET text = v.text
FROM (VALUES
('PG-SEC-005', 'tr', 'MEANING', 'pg_hba.conf''taki bazı satırlar istemcileri zayıf bir yöntemle içeri alıyor. Her adrese açık bir satır bir seviye daha önemlidir. Her satırın nedeni tablodaki Neden kolonunda.'),
('PG-SEC-005', 'tr', 'CAUSES', E'- Kurulumda ya da test sırasında kolaylık için trust ya da her adrese açık bir satır (0.0.0.0/0) bırakılmış\n- Bir uygulamanın bağlanamaması geçici olarak trust ile çözülmüş ve geri alınmamış\n- Eski sürümlerden kalma md5 ayarları scram''a taşınmamış'),
('PG-SEC-005', 'tr', 'IMPACT', E'Şimdi: tablodaki satırların kapsadığı adreslerden ve kullanıcılarla zayıf bir yöntemle bağlanılabiliyor. trust şifre sormaz (yerel socket''te sunucudaki her işletim sistemi kullanıcısı, postgres dahil her veritabanı kullanıcısı olabilir), password şifreyi ağda açık metin gönderir, md5 scram-sha-256''dan zayıftır. Her adrese açık bir satırda bu, sunucunun portuna ulaşabilen herkes için geçerlidir.\nBöyle devam ederse: ağdaki ele geçirilmiş bir makine ya da şifreleri deneyerek bulan biri, satırın kapsadığı herhangi bir veritabanı kullanıcısı olarak bağlanıp veriyi okuyabilir, değiştirebilir ya da silebilir.'),
('PG-SEC-005', 'en', 'MEANING', 'Some pg_hba.conf lines let clients in with a weak method. A line open to every address is one level more serious. Each line''s reason is in the Why column of the table.'),
('PG-SEC-005', 'en', 'CAUSES', E'- trust, or a line open to every address (0.0.0.0/0), was left from installation or testing for convenience\n- An application that could not connect was fixed with trust and never reverted\n- md5 settings from older versions were not moved to scram'),
('PG-SEC-005', 'en', 'IMPACT', E'Now: from the addresses and as the users the lines in the table cover, clients connect with a weak method. trust asks no password (on the local socket any operating system user on the server can be any database user, postgres included), password sends it in clear text over the network, md5 is weaker than scram-sha-256. On a line open to every address this holds for anyone who can reach the server''s port.\nIf it goes on: a compromised machine on the network, or someone who guesses passwords, can connect as any database user the line covers and read, change or delete data.')
) AS v (rule_key, language_code, text_type, text)
JOIN keystone.rule_definition rd ON rd.rule_key = v.rule_key
WHERE rt.rule_id = rd.rule_id
  AND rt.language_code = v.language_code
  AND rt.text_type = v.text_type;
