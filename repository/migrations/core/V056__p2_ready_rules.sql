/*
===============================================================================
Migration No : 056
Version      : V056
Title        : P2 Rules On Existing Evidence

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds eight P2 rules whose evidence is already collected:
PG-TRAN-007 Long Running Query and PG-TRAN-006 Freeze Falling Behind
(PG_TRANSACTION_HEALTH), PG-MAINT-003 Table Never Processed By Autovacuum
(PG_MAINTENANCE_HEALTH), PG-CAP-004 Memory Pressure (PG_CAPACITY_HEALTH),
PG-HA-002 Recently Restarted Server, PG-HA-003 Replica Smaller Than Primary and
PG-HA-004 Mixed PostgreSQL Versions (PG_REPLICATION_HEALTH), PG-CONF-005
Diagnostics Disabled (PG_CONFIGURATION_HEALTH).
===============================================================================
*/


/*
Design notes (2026-11-10, Hasan)
--------------------------------
Thresholds are first values to be calibrated on real systems; they are
Dictionary rows and change without code.
- PG-TRAN-007: an active statement of a client backend running 5 / 30 minutes.
  Replication senders, autovacuum and background workers are not client
  backends. A long query inside a long transaction also matches PG-TRAN-003:
  one judges the statement, the other the transaction.
- PG-TRAN-006: database XID age as a share of the primary's
  autovacuum_freeze_max_age, 150 / 200 %. At 100 % anti-wraparound autovacuum
  starts; staying well above it means freezing does not keep up. Much earlier
  than PG-TRAN-002, which judges the absolute distance to wraparound. Per-table
  autovacuum_freeze_max_age is not considered.
- PG-MAINT-003: a table with no vacuum and no analyze, manual or automatic,
  since the statistics were reset, although its changes passed twice the
  point at which autovacuum should have analyzed it (autovacuum_analyze_threshold
  + autovacuum_analyze_scale_factor × live rows, server settings; per-table
  settings are not considered) and at least min_changes rows. A missing
  timestamp alone is not a finding (catalogue constraint).
- PG-CAP-004: swap in use and little available memory together. Swap in use
  alone is misleading: pages swapped out long ago stay there. A snapshot cannot
  show swap activity (si/so); this is pressure now, not a trend.
- PG-HA-002: a server started within the window is INFO: context for other
  findings (statistics may have been reset, caches are cold).
- PG-HA-003: a replica with fewer CPUs or under 90 % of the primary's memory
  cannot carry the load after a failover.
- PG-HA-004: servers of one system on different PostgreSQL versions. Physical
  replication needs the same major version; minor differences are expected
  only during a rolling update.
- PG-CONF-005: log_lock_waits off, or pg_stat_statements not loaded:
  root-cause analysis is not possible later. INFO. log_min_duration_statement
  is judged by PG-CONF-003 and not here.
===============================================================================
*/


/* ============================================================================
   RULE DEFINITIONS
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source,
       r.default_severity, r.finding_template, r.recommendation, r.topic_key
FROM (VALUES
    ('PG_TRANSACTION_HEALTH', 'PG-TRAN-007', 'Long Running Query',
     'Detects client statements that have been running for a long time.',
     'PG_ACTIVITY_SNAPSHOT', NULL,
     'Session {pid} has been running its current statement for {running_seconds} seconds.',
     'Find out what the statement is waiting for or doing; check its plan and locks, and cancel it with pg_cancel_backend only if it is safe to do so.',
     'TRANSACTIONS'),
    ('PG_TRANSACTION_HEALTH', 'PG-TRAN-006', 'Freeze Falling Behind',
     'Detects databases whose transaction ID age stays well above autovacuum_freeze_max_age: freezing does not keep up.',
     'PG_TRANSACTION_WRAPAROUND', NULL,
     'Database {database_name} has XID age {xid_age}, {percent}% of autovacuum_freeze_max_age ({freeze_max_age}).',
     'Find the tables with the oldest relfrozenxid, check what stops vacuum from freezing them (long transactions, replication slots, prepared transactions) and run VACUUM (FREEZE) on them.',
     'MAINTENANCE'),
    ('PG_MAINTENANCE_HEALTH', 'PG-MAINT-003', 'Table Never Processed By Autovacuum',
     'Detects active tables without any vacuum or analyze since the statistics were reset.',
     'PG_VACUUM_ANALYZE', 'WARNING',
     'Table {table} has had no vacuum or analyze since the statistics were reset although {changed_rows} rows changed.',
     'Check whether autovacuum is disabled for the table (reloptions) or cannot reach it, then run VACUUM (ANALYZE) on it.',
     'MAINTENANCE'),
    ('PG_CAPACITY_HEALTH', 'PG-CAP-004', 'Memory Pressure',
     'Detects servers using swap while little memory is available.',
     'PG_HOST_SNAPSHOT', 'WARNING',
     '{node}: {available} of {memory} memory available ({available_percent}%), {swap_used} of {swap_total} swap in use ({swap_percent}%).',
     'Find what uses the memory (PostgreSQL work_mem and connections, other processes) and reduce it or add memory.',
     'STORAGE'),
    ('PG_REPLICATION_HEALTH', 'PG-HA-002', 'Recently Restarted Server',
     'Reports servers started within the recent restart window: context for other findings.',
     'PG_INSTANCE_INVENTORY', 'INFO',
     '{node_name} started at {started_at}, {since_seconds} seconds ago.',
     'If the restart was not planned, find its cause in the PostgreSQL and system logs.',
     'REPLICATION'),
    ('PG_REPLICATION_HEALTH', 'PG-HA-003', 'Replica Smaller Than Primary',
     'Detects replicas with fewer CPUs or clearly less memory than the primary.',
     'PG_HOST_SNAPSHOT', 'WARNING',
     '{node} has {cpus} CPUs and {memory} memory; the primary {primary} has {primary_cpus} CPUs and {primary_memory}.',
     'Give the replica the resources of the primary, or plan which server takes over and what load it can carry.',
     'REPLICATION'),
    ('PG_REPLICATION_HEALTH', 'PG-HA-004', 'Mixed PostgreSQL Versions',
     'Detects servers of one system running different PostgreSQL versions.',
     'PG_INSTANCE_INVENTORY', 'WARNING',
     '{node_name} runs PostgreSQL {version}; the primary {primary} runs {primary_version}.',
     'Finish the update so that every server runs the same version; update replicas first, then switch over.',
     'REPLICATION'),
    ('PG_CONFIGURATION_HEALTH', 'PG-CONF-005', 'Diagnostics Disabled',
     'Detects servers where lock waits are not logged or pg_stat_statements is not loaded.',
     'PG_CONFIGURATION_SNAPSHOT', 'INFO',
     '{setting} = ''{value}'' on {node_name}.',
     'Turn on log_lock_waits and load pg_stat_statements (shared_preload_libraries, needs a restart) so that problems can be analyzed later.',
     'CONFIGURATION')
) AS r (assessment_key, rule_key, name, description, evidence_source, default_severity,
        finding_template, recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = r.assessment_key
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   THRESHOLDS, PARAMETERS, EVIDENCE, CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, t.threshold_unit
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-007', 'WARNING',  300,  'SECOND'),
    ('PG-TRAN-007', 'CRITICAL', 1800, 'SECOND'),
    ('PG-TRAN-006', 'WARNING',  150,  'PERCENT'),
    ('PG-TRAN-006', 'CRITICAL', 200,  'PERCENT')
) AS t (rule_key, severity, threshold_value, threshold_unit) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rd.rule_id, p.parameter_key, p.parameter_value, p.parameter_unit, p.description
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-MAINT-003', 'min_changes', 10000, 'ROW',
     'A table with fewer changed rows is not judged.'),
    ('PG-MAINT-003', 'overdue_factor', 2, 'RATIO',
     'Changed rows must pass this multiple of the point at which autovacuum should have analyzed the table.'),
    ('PG-CAP-004', 'max_available_memory', 10, 'PERCENT',
     'Available memory below this share of the total is low.'),
    ('PG-CAP-004', 'min_swap_used', 10, 'PERCENT',
     'Swap in use from this share of the swap space counts.'),
    ('PG-HA-002', 'recent_restart_window', 86400, 'SECOND',
     'A server started this recently is reported.'),
    ('PG-HA-003', 'min_memory_share', 90, 'PERCENT',
     'A replica with less memory than this share of the primary''s is smaller.')
) AS p (rule_key, parameter_key, parameter_value, parameter_unit, description) ON p.rule_key = rd.rule_key
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, e.evidence_source, e.is_required, e.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-007',  'PG_ACTIVITY_SNAPSHOT',      TRUE,  600),
    ('PG-TRAN-006',  'PG_TRANSACTION_WRAPAROUND', TRUE,  86400),
    ('PG-TRAN-006',  'PG_CONFIGURATION_SNAPSHOT', TRUE,  86400),
    ('PG-TRAN-006',  'PG_INSTANCE_INVENTORY',     TRUE,  3600),
    ('PG-MAINT-003', 'PG_VACUUM_ANALYZE',         TRUE,  86400),
    ('PG-MAINT-003', 'PG_CONFIGURATION_SNAPSHOT', FALSE, 86400),
    ('PG-CAP-004',   'PG_HOST_SNAPSHOT',          TRUE,  3600),
    ('PG-HA-002',    'PG_INSTANCE_INVENTORY',     TRUE,  3600),
    ('PG-HA-003',    'PG_HOST_SNAPSHOT',          TRUE,  3600),
    ('PG-HA-003',    'PG_INSTANCE_INVENTORY',     TRUE,  3600),
    ('PG-HA-004',    'PG_INSTANCE_INVENTORY',     TRUE,  3600),
    ('PG-CONF-005',  'PG_CONFIGURATION_SNAPSHOT', TRUE,  86400)
) AS e (rule_key, evidence_source, is_required, max_age_seconds) ON e.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-007',  'PERFORMANCE'),
    ('PG-TRAN-007',  'AVAILABILITY'),
    ('PG-TRAN-006',  'AVAILABILITY'),
    ('PG-MAINT-003', 'PERFORMANCE'),
    ('PG-CAP-004',   'PERFORMANCE'),
    ('PG-CAP-004',   'AVAILABILITY'),
    ('PG-HA-002',    'AVAILABILITY'),
    ('PG-HA-003',    'AVAILABILITY'),
    ('PG-HA-003',    'PERFORMANCE'),
    ('PG-HA-004',    'AVAILABILITY'),
    ('PG-CONF-005',  'PERFORMANCE')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
-- PG-TRAN-007 ---------------------------------------------------------------
('PG-TRAN-007', 'tr', 'NAME', 'Uzun süren sorgu'),
('PG-TRAN-007', 'tr', 'HEALTHY', 'Çalışma süresi {warning} sınırını aşan sorgu yok.'),
('PG-TRAN-007', 'tr', 'MEANING', 'Bazı oturumlarda tek bir sorgu uzun süredir çalışıyor.'),
('PG-TRAN-007', 'tr', 'CAUSES', E'- Sorgu uygun bir index bulamıyor ya da planı kötü (eski istatistikler, yanlış tahmin)\n- Sorgu bir kilidi bekliyor\n- Büyük bir rapor, toplu güncelleme ya da yedek (pg_dump) çalışıyor\n- İstemci sorguyu bırakmış ama sunucu tarafında iptal edilmemiş'),
('PG-TRAN-007', 'tr', 'IMPACT', 'Uzun süren sorgu CPU ve disk tüketir, tuttuğu kilitler diğer işlemleri bekletebilir ve vacuum''un eski satırları temizlemesini engeller.'),
('PG-TRAN-007', 'tr', 'RECOMMENDATION', E'- Sorgunun ne beklediğine bakın (wait_event, pg_locks)\n- Sorgunun planını EXPLAIN ile inceleyin; eksik index ya da eski istatistik olup olmadığını kontrol edin\n- Güvenliyse pg_cancel_backend ile iptal edin; uygulama sahibine danışmadan sonlandırmayın\n- Tekrarlıyorsa statement_timeout tanımlamayı düşünün'),
('PG-TRAN-007', 'tr', 'FINDING', '{pid} numaralı oturumdaki sorgu {running_seconds} süredir çalışıyor.'),
('PG-TRAN-007', 'en', 'NAME', 'Long running query'),
('PG-TRAN-007', 'en', 'HEALTHY', 'No statement has been running longer than {warning}.'),
('PG-TRAN-007', 'en', 'MEANING', 'In some sessions a single statement has been running for a long time.'),
('PG-TRAN-007', 'en', 'CAUSES', E'- The statement finds no suitable index or has a poor plan (stale statistics, wrong estimates)\n- The statement is waiting for a lock\n- A large report, bulk update or backup (pg_dump) is running\n- The client gave up on the statement but it was not cancelled on the server'),
('PG-TRAN-007', 'en', 'IMPACT', 'A long statement uses CPU and disk, the locks it holds can make other work wait, and it stops vacuum from removing old rows.'),
('PG-TRAN-007', 'en', 'RECOMMENDATION', E'- Check what the statement is waiting for (wait_event, pg_locks)\n- Examine its plan with EXPLAIN; look for a missing index or stale statistics\n- If it is safe, cancel it with pg_cancel_backend; do not terminate it without the application owner\n- If it recurs, consider a statement_timeout'),
('PG-TRAN-007', 'en', 'FINDING', 'Session {pid} has been running its current statement for {running_seconds}.'),
-- PG-TRAN-006 ---------------------------------------------------------------
('PG-TRAN-006', 'tr', 'NAME', 'Freeze işleminin gerisinde kalma'),
('PG-TRAN-006', 'tr', 'HEALTHY', 'Hiçbir veritabanında transaction ID yaşı autovacuum_freeze_max_age değerinin {warning} kadarına ulaşmamış.'),
('PG-TRAN-006', 'tr', 'MEANING', 'Bazı veritabanlarında transaction ID yaşı, autovacuum''un freeze işlemine başladığı sınırın (autovacuum_freeze_max_age) belirgin şekilde üzerinde kalıyor.'),
('PG-TRAN-006', 'tr', 'CAUSES', E'- Uzun süren transaction, unutulmuş bir replication slot ya da prepared transaction vacuum''un eski satırları freeze etmesini engelliyor\n- Çok büyük tablolarda freeze vacuum''u yetişemiyor (autovacuum yavaş ya da sık kesiliyor)\n- Autovacuum bazı tablolar için kapatılmış'),
('PG-TRAN-006', 'tr', 'IMPACT', 'Durum devam ederse transaction ID wraparound sınırına yaklaşılır; o noktada PostgreSQL veri güvenliği için yeni transaction kabul etmeyi durdurur. Bu kural bunu PG-TRAN-002''den çok önce, hâlâ zaman varken gösterir.'),
('PG-TRAN-006', 'tr', 'RECOMMENDATION', E'- relfrozenxid''i en eski tabloları bulun (age(relfrozenxid) sırasıyla)\n- Freeze''i engelleyen uzun transaction, replication slot ya da prepared transaction olup olmadığını kontrol edin\n- Bu tablolarda yoğun olmayan bir saatte VACUUM (FREEZE) çalıştırın\n- Gerekirse autovacuum_vacuum_cost_limit ve worker sayısını artırın'),
('PG-TRAN-006', 'tr', 'FINDING', '{database_name} veritabanında transaction ID yaşı {xid_age}; autovacuum_freeze_max_age değerinin ({freeze_max_age}) %{percent} kadarı.'),
('PG-TRAN-006', 'en', 'NAME', 'Freeze falling behind'),
('PG-TRAN-006', 'en', 'HEALTHY', 'No database has a transaction ID age of {warning} of autovacuum_freeze_max_age.'),
('PG-TRAN-006', 'en', 'MEANING', 'In some databases the transaction ID age stays clearly above the point where autovacuum starts freezing (autovacuum_freeze_max_age).'),
('PG-TRAN-006', 'en', 'CAUSES', E'- A long transaction, a forgotten replication slot or a prepared transaction stops vacuum from freezing old rows\n- Freezing cannot keep up on very large tables (autovacuum slow or often interrupted)\n- Autovacuum is disabled for some tables'),
('PG-TRAN-006', 'en', 'IMPACT', 'If it continues, transaction ID wraparound comes closer; at that point PostgreSQL stops accepting new transactions to protect the data. This rule shows it long before PG-TRAN-002, while there is still time.'),
('PG-TRAN-006', 'en', 'RECOMMENDATION', E'- Find the tables with the oldest relfrozenxid (ordered by age(relfrozenxid))\n- Check for a long transaction, replication slot or prepared transaction holding freezing back\n- Run VACUUM (FREEZE) on those tables at a quiet time\n- If needed, raise autovacuum_vacuum_cost_limit and the number of workers'),
('PG-TRAN-006', 'en', 'FINDING', 'Database {database_name} has a transaction ID age of {xid_age}, {percent}% of autovacuum_freeze_max_age ({freeze_max_age}).'),
-- PG-MAINT-003 --------------------------------------------------------------
('PG-MAINT-003', 'tr', 'NAME', 'Autovacuum''un hiç işlemediği tablo'),
('PG-MAINT-003', 'tr', 'HEALTHY', 'Çok değişiklik gördüğü halde hiç vacuum ya da analyze çalışmamış tablo yok.'),
('PG-MAINT-003', 'tr', 'MEANING', 'Bazı tablolarda, istatistikler sıfırlandığından beri çok satır değiştiği halde ne vacuum ne de analyze (elle ya da autovacuum ile) çalışmış.'),
('PG-MAINT-003', 'tr', 'CAUSES', E'- Autovacuum bu tablo için kapatılmış (autovacuum_enabled = false)\n- Autovacuum worker''ları başka büyük tablolarla meşgul ve bu tabloya sıra gelmiyor\n- Tablo üzerindeki uzun süren kilitler autovacuum''un çalışmasını engelliyor'),
('PG-MAINT-003', 'tr', 'IMPACT', 'İstatistikler güncel olmadığı için sorgu planları bozulabilir; dead tuple''lar temizlenmediği için tablo şişer ve sorgular yavaşlar.'),
('PG-MAINT-003', 'tr', 'RECOMMENDATION', E'- Tablonun ayarlarında autovacuum''un kapatılıp kapatılmadığını kontrol edin (pg_class.reloptions)\n- Tabloda VACUUM (ANALYZE) çalıştırın\n- Autovacuum''un neden ulaşamadığını pg_stat_activity ve log''larla inceleyin'),
('PG-MAINT-003', 'tr', 'FINDING', '{table} tablosunda istatistikler sıfırlandığından beri {changed_rows} satır değiştiği halde hiç vacuum ya da analyze çalışmamış.'),
('PG-MAINT-003', 'en', 'NAME', 'Table never processed by autovacuum'),
('PG-MAINT-003', 'en', 'HEALTHY', 'No table with many changes is missing every vacuum and analyze.'),
('PG-MAINT-003', 'en', 'MEANING', 'Some tables have had neither vacuum nor analyze (manual or autovacuum) since the statistics were reset, although many of their rows changed.'),
('PG-MAINT-003', 'en', 'CAUSES', E'- Autovacuum is disabled for the table (autovacuum_enabled = false)\n- Autovacuum workers are busy with other large tables and never reach this one\n- Long-held locks on the table stop autovacuum'),
('PG-MAINT-003', 'en', 'IMPACT', 'Outdated statistics can spoil query plans; dead rows are not removed, so the table bloats and queries slow down.'),
('PG-MAINT-003', 'en', 'RECOMMENDATION', E'- Check whether autovacuum is disabled in the table''s settings (pg_class.reloptions)\n- Run VACUUM (ANALYZE) on the table\n- Find out why autovacuum does not reach it from pg_stat_activity and the logs'),
('PG-MAINT-003', 'en', 'FINDING', 'Table {table} has had no vacuum or analyze since the statistics were reset although {changed_rows} rows changed.'),
-- PG-CAP-004 ----------------------------------------------------------------
('PG-CAP-004', 'tr', 'NAME', 'Bellek baskısı'),
('PG-CAP-004', 'tr', 'HEALTHY', 'Hiçbir sunucuda swap kullanılırken kullanılabilir bellek azalmış değil.'),
('PG-CAP-004', 'tr', 'MEANING', 'Bazı sunucularda kullanılabilir bellek çok azalmış ve işletim sistemi swap kullanıyor.'),
('PG-CAP-004', 'tr', 'CAUSES', E'- work_mem ve bağlantı sayısı birlikte sunucunun belleğini aşıyor\n- Sunucuda PostgreSQL dışında çok bellek kullanan süreçler var\n- shared_buffers sunucunun belleğine göre çok büyük'),
('PG-CAP-004', 'tr', 'IMPACT', 'Swap kullanımı sorguları belirgin şekilde yavaşlatır; bellek tamamen biterse işletim sistemi PostgreSQL süreçlerini sonlandırabilir (OOM killer) ve sunucu yeniden başlar.'),
('PG-CAP-004', 'tr', 'RECOMMENDATION', E'- Belleği hangi süreçlerin kullandığını bulun (top, ps)\n- work_mem, max_connections ve shared_buffers ayarlarını sunucunun belleğine göre gözden geçirin; çok bağlantı varsa connection pooler kullanın\n- Gerekirse sunucuya bellek ekleyin'),
('PG-CAP-004', 'tr', 'FINDING', '{node}: {memory} belleğin {available} kadarı kullanılabilir (%{available_percent}); {swap_total} swap''in {swap_used} kadarı kullanımda (%{swap_percent}).'),
('PG-CAP-004', 'en', 'NAME', 'Memory pressure'),
('PG-CAP-004', 'en', 'HEALTHY', 'No server is using swap while short of available memory.'),
('PG-CAP-004', 'en', 'MEANING', 'On some servers little memory is available and the operating system is using swap.'),
('PG-CAP-004', 'en', 'CAUSES', E'- work_mem and the number of connections together exceed the server''s memory\n- Other processes on the server use much memory\n- shared_buffers is too large for the server''s memory'),
('PG-CAP-004', 'en', 'IMPACT', 'Swapping slows queries down markedly; if memory runs out, the operating system can kill PostgreSQL processes (OOM killer) and the server restarts.'),
('PG-CAP-004', 'en', 'RECOMMENDATION', E'- Find which processes use the memory (top, ps)\n- Review work_mem, max_connections and shared_buffers against the server''s memory; use a connection pooler for many connections\n- Add memory if needed'),
('PG-CAP-004', 'en', 'FINDING', '{node}: {available} of {memory} memory available ({available_percent}%), {swap_used} of {swap_total} swap in use ({swap_percent}%).'),
-- PG-HA-002 -----------------------------------------------------------------
('PG-HA-002', 'tr', 'NAME', 'Yakın zamanda yeniden başlamış sunucu'),
('PG-HA-002', 'tr', 'HEALTHY', 'Son 24 saatte yeniden başlamış sunucu yok.'),
('PG-HA-002', 'tr', 'MEANING', 'Bazı sunucularda PostgreSQL son 24 saat içinde başlatılmış.'),
('PG-HA-002', 'tr', 'CAUSES', E'- Planlı bakım, sürüm güncellemesi ya da ayar değişikliği için restart\n- Failover ya da switchover\n- Çökme, bellek tükenmesi (OOM killer) ya da sunucunun yeniden başlaması'),
('PG-HA-002', 'tr', 'IMPACT', 'Restart sonrasında önbellekler boştur ve bazı istatistikler sıfırlanmış olabilir; bu kontrolün diğer bulguları bu bağlamla yorumlanmalıdır. Planlanmamışsa kesintinin sebebi bilinmelidir.'),
('PG-HA-002', 'tr', 'RECOMMENDATION', E'- Restart planlı değilse sebebini PostgreSQL ve sistem log''larında arayın\n- Çökme ya da OOM izleri varsa bellek ayarlarını ve sunucunun durumunu inceleyin'),
('PG-HA-002', 'tr', 'FINDING', '{node_name} {started_at} zamanında başlatılmış ({since_seconds} önce).'),
('PG-HA-002', 'en', 'NAME', 'Recently restarted server'),
('PG-HA-002', 'en', 'HEALTHY', 'No server was restarted in the last 24 hours.'),
('PG-HA-002', 'en', 'MEANING', 'On some servers PostgreSQL was started within the last 24 hours.'),
('PG-HA-002', 'en', 'CAUSES', E'- A restart for planned maintenance, an update or a setting change\n- A failover or switchover\n- A crash, memory exhaustion (OOM killer) or a server reboot'),
('PG-HA-002', 'en', 'IMPACT', 'After a restart caches are empty and some statistics may have been reset; the other findings of this check should be read with that in mind. If it was not planned, the cause of the outage should be known.'),
('PG-HA-002', 'en', 'RECOMMENDATION', E'- If the restart was not planned, look for its cause in the PostgreSQL and system logs\n- If there are signs of a crash or the OOM killer, review the memory settings and the server'),
('PG-HA-002', 'en', 'FINDING', '{node_name} started at {started_at}, {since_seconds} ago.'),
-- PG-HA-003 -----------------------------------------------------------------
('PG-HA-003', 'tr', 'NAME', 'Primary''den küçük replica'),
('PG-HA-003', 'tr', 'HEALTHY', 'Bütün replica''lar CPU ve bellek olarak primary ile denk.'),
('PG-HA-003', 'tr', 'MEANING', 'Bazı replica''ların CPU sayısı ya da belleği primary''ninkinden belirgin şekilde az.'),
('PG-HA-003', 'tr', 'CAUSES', E'- Replica, raporlama ya da yedek amaçlı daha küçük bir sunucuya kuruldu\n- Primary büyütüldü ama replica''lar büyütülmedi'),
('PG-HA-003', 'tr', 'IMPACT', 'Failover sonrasında bu replica primary olursa aynı yükü taşıyamayabilir; sistem yavaşlar ya da bellek yetmez.'),
('PG-HA-003', 'tr', 'RECOMMENDATION', E'- Replica''ya primary ile aynı kaynakları verin\n- Bu bilinçli bir tercihse, failover''da hangi sunucunun primary olacağını ve taşıyabileceği yükü planlayın (örneğin Patroni''de nofailover etiketi)'),
('PG-HA-003', 'tr', 'FINDING', '{node}: {cpus} CPU ve {memory} bellek; primary {primary}: {primary_cpus} CPU ve {primary_memory}.'),
('PG-HA-003', 'en', 'NAME', 'Replica smaller than primary'),
('PG-HA-003', 'en', 'HEALTHY', 'Every replica matches the primary in CPUs and memory.'),
('PG-HA-003', 'en', 'MEANING', 'Some replicas have clearly fewer CPUs or less memory than the primary.'),
('PG-HA-003', 'en', 'CAUSES', E'- The replica was set up on a smaller server for reporting or backups\n- The primary was enlarged but the replicas were not'),
('PG-HA-003', 'en', 'IMPACT', 'If this replica becomes primary after a failover it may not carry the same load; the system slows down or runs out of memory.'),
('PG-HA-003', 'en', 'RECOMMENDATION', E'- Give the replica the same resources as the primary\n- If this is a deliberate choice, plan which server becomes primary on failover and what load it can carry (for example the nofailover tag in Patroni)'),
('PG-HA-003', 'en', 'FINDING', '{node} has {cpus} CPUs and {memory} memory; the primary {primary} has {primary_cpus} CPUs and {primary_memory}.'),
-- PG-HA-004 -----------------------------------------------------------------
('PG-HA-004', 'tr', 'NAME', 'Sunucular arasında farklı PostgreSQL sürümü'),
('PG-HA-004', 'tr', 'HEALTHY', 'Bütün sunucular aynı PostgreSQL sürümünü çalıştırıyor.'),
('PG-HA-004', 'tr', 'MEANING', 'Aynı sistemin sunucuları farklı PostgreSQL sürümlerini çalıştırıyor.'),
('PG-HA-004', 'tr', 'CAUSES', E'- Sürüm güncellemesi bir kısım sunucuda yapıldı, diğerlerinde yarım kaldı\n- Paket güncellemesi sunucularda farklı zamanlarda çalıştı'),
('PG-HA-004', 'tr', 'IMPACT', 'Farklı minor sürümler bir güncelleme sırasında beklenir ama kalıcı olmamalıdır: bazı düzeltmeler yalnızca bir kısım sunucuda vardır ve failover sonrasında davranış değişebilir.'),
('PG-HA-004', 'tr', 'RECOMMENDATION', E'- Güncellemeyi tamamlayın; önce replica''ları güncelleyin, sonra switchover yapıp eski primary''yi güncelleyin\n- Paket güncellemelerinin bütün sunucularda birlikte yapılmasını süreçlere ekleyin'),
('PG-HA-004', 'tr', 'FINDING', '{node_name} PostgreSQL {version} çalıştırıyor; primary {primary} ise {primary_version}.'),
('PG-HA-004', 'en', 'NAME', 'Mixed PostgreSQL versions'),
('PG-HA-004', 'en', 'HEALTHY', 'Every server runs the same PostgreSQL version.'),
('PG-HA-004', 'en', 'MEANING', 'The servers of one system run different PostgreSQL versions.'),
('PG-HA-004', 'en', 'CAUSES', E'- An update was done on some servers and not finished on the others\n- Package updates ran on the servers at different times'),
('PG-HA-004', 'en', 'IMPACT', 'Different minor versions are expected during an update but should not stay: some fixes exist on only some servers, and behaviour can change after a failover.'),
('PG-HA-004', 'en', 'RECOMMENDATION', E'- Finish the update; update the replicas first, then switch over and update the old primary\n- Make updating all servers together part of the process'),
('PG-HA-004', 'en', 'FINDING', '{node_name} runs PostgreSQL {version}; the primary {primary} runs {primary_version}.'),
-- PG-CONF-005 ---------------------------------------------------------------
('PG-CONF-005', 'tr', 'NAME', 'Teşhis ayarları kapalı'),
('PG-CONF-005', 'tr', 'HEALTHY', 'Kilit beklemeleri loglanıyor ve pg_stat_statements yüklü.'),
('PG-CONF-005', 'tr', 'MEANING', 'Bazı sunucularda kilit beklemeleri loglanmıyor ya da sorgu istatistiklerini tutan pg_stat_statements yüklü değil.'),
('PG-CONF-005', 'tr', 'CAUSES', E'- Varsayılan ayarlar değiştirilmedi (ikisi de varsayılan olarak kapalı)\n- pg_stat_statements''in yükü konusunda yanlış bir endişe'),
('PG-CONF-005', 'tr', 'IMPACT', 'Bir yavaşlık ya da kilitlenme yaşandığında hangi sorgunun ve hangi kilidin sebep olduğu sonradan bulunamaz; kök neden analizi tahmine dayanır.'),
('PG-CONF-005', 'tr', 'RECOMMENDATION', E'- log_lock_waits = on yapın (reload yeterli)\n- shared_preload_libraries''e pg_stat_statements ekleyin (restart gerekir) ve izlenen veritabanında CREATE EXTENSION pg_stat_statements çalıştırın'),
('PG-CONF-005', 'tr', 'FINDING', '{node_name} üzerinde {setting} = {value}; kilit beklemeleri loglanmıyor.'),
('PG-CONF-005', 'tr', 'FINDING_ALT', '{node_name} üzerinde pg_stat_statements yüklü değil (shared_preload_libraries = ''{value}'').'),
('PG-CONF-005', 'en', 'NAME', 'Diagnostics disabled'),
('PG-CONF-005', 'en', 'HEALTHY', 'Lock waits are logged and pg_stat_statements is loaded.'),
('PG-CONF-005', 'en', 'MEANING', 'On some servers lock waits are not logged or pg_stat_statements, which keeps query statistics, is not loaded.'),
('PG-CONF-005', 'en', 'CAUSES', E'- The defaults were not changed (both are off by default)\n- A mistaken concern about the overhead of pg_stat_statements'),
('PG-CONF-005', 'en', 'IMPACT', 'When a slowdown or lock pile-up happens, which statement and which lock caused it cannot be found afterwards; root-cause analysis becomes guesswork.'),
('PG-CONF-005', 'en', 'RECOMMENDATION', E'- Set log_lock_waits = on (a reload is enough)\n- Add pg_stat_statements to shared_preload_libraries (needs a restart) and run CREATE EXTENSION pg_stat_statements in the monitored database'),
('PG-CONF-005', 'en', 'FINDING', '{setting} = {value} on {node_name}; lock waits are not logged.'),
('PG-CONF-005', 'en', 'FINDING_ALT', 'pg_stat_statements is not loaded on {node_name} (shared_preload_libraries = ''{value}'').')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
