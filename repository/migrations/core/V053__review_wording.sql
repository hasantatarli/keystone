/*
===============================================================================
Migration No : 053
Version      : V053
Title        : Review Wording

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
External review 2026-11-09, step C: texts claim only what the evidence
shows. PG-CONF-007 becomes a WARNING configuration risk indicator; WAL
archiving, SSL and failover texts separate the observation from the
conclusion.
===============================================================================
*/


/*
Notes
-----
- PG-CONF-007: shared_buffers + max_connections × work_mem is pessimistic (not
  every connection uses work_mem at once) and also optimistic (one query can
  use it several times, parallel workers add more). It indicates a risk, it
  does not measure memory use; its HEALTHY text does not promise memory health.
- PG-BKP-002: archiving off means no point-in-time recovery from a WAL archive;
  it does not mean there is no backup (snapshots, pg_dump, a backup service).
- PG-SEC-003: the server does not accept TLS; encryption elsewhere (VPN, a
  proxy) is not visible to this check.
- PG-HA-001: the time comes from the history file of the current timeline
  (approximate, a copy or restore changes it); planned switchover and failover
  look the same.
===============================================================================
*/


UPDATE keystone.rule_definition
SET default_severity = 'WARNING',
    name = 'Memory Overcommitment Risk',
    description = 'Configuration risk indicator: shared_buffers plus max_connections times work_mem above a server''s memory.',
    finding_template = 'On {node} shared_buffers ({shared_buffers}) plus max_connections × work_mem ({max_connections} × {work_mem}) is {committed}, more than its memory ({memory}): a potential risk, not measured use.'
WHERE rule_key = 'PG-CONF-007';

UPDATE keystone.rule_text rt
SET text = v.text
FROM (VALUES
('PG-CONF-007', 'tr', 'NAME', 'Bellek aşırı taahhüdü riski'),
('PG-CONF-007', 'tr', 'HEALTHY', 'Değerlendirilen ayarlar (shared_buffers + max_connections × work_mem) bu hesaplamanın bellek risk eşiğini aşmıyor; bu, sistemin genel bellek sağlığını garanti etmez.'),
('PG-CONF-007', 'tr', 'MEANING', 'Konfigürasyondan hesaplanan potansiyel bellek riski: shared_buffers ile max_connections × work_mem toplamı sunucunun belleğinden büyük. Bu gerçek bellek tüketimi değildir; bağlantılar aynı anda çok bellek isterse baskı oluşabileceğini gösterir.'),
('PG-CONF-007', 'tr', 'IMPACT', 'Bağlantılar aynı anda bellek isterse işletim sistemi PostgreSQL süreçlerini sonlandırabilir (OOM killer); bu tüm veritabanının yeniden başlaması demektir. Gerçekte ne kadar bellek kullanıldığı iş yüküne bağlıdır.'),
('PG-CONF-007', 'tr', 'FINDING', '{node} sunucusunda shared_buffers ({shared_buffers}) ile max_connections × work_mem ({max_connections} × {work_mem}) toplamı {committed}; sunucunun belleğinden ({memory}) büyük. Ölçülen kullanım değil, potansiyel risk.'),
('PG-CONF-007', 'en', 'NAME', 'Memory overcommitment risk'),
('PG-CONF-007', 'en', 'HEALTHY', 'The settings assessed (shared_buffers + max_connections × work_mem) stay below this calculation''s memory risk limit; this does not guarantee the system''s memory health.'),
('PG-CONF-007', 'en', 'MEANING', 'A potential memory risk calculated from the configuration: shared_buffers plus max_connections × work_mem is larger than the server''s memory. It is not measured use; it shows that pressure can build if connections ask for much memory at once.'),
('PG-CONF-007', 'en', 'IMPACT', 'If connections ask for memory at once, the operating system can kill PostgreSQL processes (OOM killer), which restarts the whole database. How much memory is really used depends on the workload.'),
('PG-CONF-007', 'en', 'FINDING', 'On {node} shared_buffers ({shared_buffers}) plus max_connections × work_mem ({max_connections} × {work_mem}) is {committed}, more than its memory ({memory}): a potential risk, not measured use.'),

('PG-BKP-002', 'tr', 'IMPACT', 'Arşivleme kapalıysa WAL arşivinden belirli bir ana geri dönüş (point-in-time recovery) yapılamaz. Bu, yedek olmadığı anlamına gelmez: yedek disk snapshot''ı, pg_dump ya da bir yedekleme servisiyle alınıyor olabilir; bu kontrol bunu göremez. Arşivleme açık ama komut boşsa WAL dosyaları silinmez ve disk dolar.'),
('PG-BKP-002', 'en', 'IMPACT', 'With archiving off there is no point-in-time recovery from a WAL archive. This does not mean there is no backup: backups may be taken with disk snapshots, pg_dump or a backup service, which this check cannot see. With archiving on and no command, WAL files are never removed and the disk fills up.'),

('PG-SEC-003', 'tr', 'MEANING', 'Sunucu şifreli (SSL/TLS) bağlantı kabul etmiyor; istemciler bu sunucuya şifresiz bağlanıyor. Ağda başka bir şifreleme (VPN, şifreleyen bir proxy) olup olmadığını bu kontrol göremez.'),
('PG-SEC-003', 'en', 'MEANING', 'The server does not accept encrypted (SSL/TLS) connections; clients connect to it unencrypted. Whether the network adds encryption elsewhere (a VPN, an encrypting proxy) is not visible to this check.'),

('PG-HA-001', 'tr', 'HEALTHY', 'Şu anki timeline''ın history dosyasına göre yakın zamanda failover ya da switchover olmamış.'),
('PG-HA-001', 'tr', 'MEANING', 'Primary yakın zamanda yeni bir timeline''a geçmiş: failover ya da switchover olmuş. Zaman, timeline''ın history dosyasından okunduğu için yaklaşıktır; planlı bir switchover ile beklenmedik bir failover bu kanıttan ayırt edilemez.'),
('PG-HA-001', 'tr', 'FINDING', 'Şu anki primary {node_name}, timeline {timeline_id}; history dosyasına göre son failover ya da switchover yaklaşık {since_seconds} önce ({timeline_started_at}).'),
('PG-HA-001', 'en', 'HEALTHY', 'According to the current timeline''s history file there was no recent failover or switchover.'),
('PG-HA-001', 'en', 'MEANING', 'The primary recently moved to a new timeline: a failover or switchover happened. The time is read from the timeline''s history file and is approximate; a planned switchover and an unexpected failover look the same in this evidence.'),
('PG-HA-001', 'en', 'FINDING', 'The current primary is {node_name}, timeline {timeline_id}; according to the history file the last failover or switchover was about {since_seconds} ago ({timeline_started_at}).')
) AS v (rule_key, language_code, text_type, text)
JOIN keystone.rule_definition rd ON rd.rule_key = v.rule_key
WHERE rt.rule_id = rd.rule_id
  AND rt.language_code = v.language_code
  AND rt.text_type = v.text_type;
