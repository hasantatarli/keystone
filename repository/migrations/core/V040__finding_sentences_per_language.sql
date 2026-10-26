/*
===============================================================================
Migration No : 040
Version      : V040
Title        : Finding Sentences per Language

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Stores the values of each finding (finding.template_values) and adds the rule
text types FINDING and FINDING_ALT, so reports phrase findings in their own
language. finding_text stays the English sentence written at evaluation time.
===============================================================================
*/


/*
Design notes (2026-10-26)
-------------------------
Finding sentences were English only (rule_definition.finding_template), also
in Turkish reports. A rule whose finding has two shapes sets "_alt" in its
template values and the report uses FINDING_ALT: PG-REP-003 for a replica with
an intended apply delay, PG-BKP-002 for archive_mode on without a command.
Findings stored before V040 have no template values and keep finding_text.
===============================================================================
*/

ALTER TABLE keystone.finding
    ADD COLUMN template_values JSONB;

COMMENT ON COLUMN keystone.finding.template_values IS
'Values the finding sentence is built from; reports format them with the FINDING text of their language. NULL before V040.';

ALTER TABLE keystone.rule_text DROP CONSTRAINT ck_rule_text_type;

ALTER TABLE keystone.rule_text
    ADD CONSTRAINT ck_rule_text_type
    CHECK (text_type IN ('NAME', 'HEALTHY', 'MEANING', 'CAUSES', 'IMPACT', 'RECOMMENDATION',
                         'FINDING', 'FINDING_ALT'));


INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

('PG-TRAN-001', 'tr', 'FINDING', '{pid} numaralı session {duration_seconds} saniyedir transaction içinde boşta bekliyor.'),
('PG-TRAN-001', 'en', 'FINDING', 'Session {pid} has been idle in transaction for {duration_seconds} seconds.'),
('PG-TRAN-002', 'tr', 'FINDING', '{database_name} veritabanının transaction ID yaşı {xid_age}.'),
('PG-TRAN-002', 'en', 'FINDING', 'Database {database_name} has a transaction ID age of {xid_age}.'),
('PG-TRAN-003', 'tr', 'FINDING', '{pid} numaralı session''da {duration_seconds} saniyedir açık bir transaction var (durum: {state}).'),
('PG-TRAN-003', 'en', 'FINDING', 'Session {pid} has had a transaction open for {duration_seconds} seconds (current state: {state}).'),
('PG-TRAN-004', 'tr', 'FINDING', '{database_name} veritabanının MultiXact ID yaşı {mxid_age}.'),
('PG-TRAN-004', 'en', 'FINDING', 'Database {database_name} has a MultiXact ID age of {mxid_age}.'),

('PG-REP-001', 'tr', 'FINDING', '{slot_name} replication slot''unun WAL durumu: {wal_status}.'),
('PG-REP-001', 'en', 'FINDING', 'Replication slot {slot_name} has WAL status {wal_status}.'),
('PG-REP-002', 'tr', 'FINDING', '{slot_name} replication slot''unun WAL durumu: {wal_status}.'),
('PG-REP-002', 'en', 'FINDING', 'Replication slot {slot_name} has WAL status {wal_status}.'),
('PG-REP-003', 'tr', 'FINDING', 'Replica {replica}, değişiklikleri primary''nin {lag_seconds} saniye gerisinden uyguluyor.'),
('PG-REP-003', 'en', 'FINDING', 'Replica {replica} is {lag_seconds} seconds behind the primary in replaying changes.'),
('PG-REP-003', 'tr', 'FINDING_ALT', 'Replica {replica}, değişiklikleri primary''nin {lag_seconds} saniye gerisinden uyguluyor; bunun {beyond_seconds} saniyesi {delay_seconds} saniyelik bilinçli gecikmenin üzerinde.'),
('PG-REP-003', 'en', 'FINDING_ALT', 'Replica {replica} is {lag_seconds} seconds behind the primary in replaying changes ({beyond_seconds} seconds beyond its intended apply delay of {delay_seconds} seconds).'),
('PG-REP-004', 'tr', 'FINDING', 'Replica {replica} primary''den veri almıyor (durum: {state}).'),
('PG-REP-004', 'en', 'FINDING', 'Replica {replica} is not streaming from the primary (state: {state}).'),
('PG-REP-005', 'tr', 'FINDING', '{slot_name} replication slot''u ({slot_type}) kullanılmıyor.'),
('PG-REP-005', 'en', 'FINDING', 'Replication slot {slot_name} ({slot_type}) is not in use.'),
('PG-REP-006', 'tr', 'FINDING', 'Synchronous replikasyon tanımlı (synchronous_standby_names = {synchronous_standby_names}) ama synchronous durumda standby yok; commit''ler gelmeyecek bir onayı bekliyor.'),
('PG-REP-006', 'en', 'FINDING', 'Synchronous replication is configured (synchronous_standby_names = {synchronous_standby_names}) but no standby is synchronous; commits wait for a confirmation that cannot come.'),

('PG-CONN-001', 'tr', 'FINDING', '{connection_count} bağlantı, hata alıp rollback edilmemiş bir transaction''da bekliyor.'),
('PG-CONN-001', 'en', 'FINDING', '{connection_count} client connection(s) are idle in an aborted transaction state.'),
('PG-CONN-002', 'tr', 'FINDING', 'Kullanılabilir {usable} bağlantının {connections} tanesi kullanımda (%{percent}).'),
('PG-CONN-002', 'en', 'FINDING', '{connections} of {usable} usable connections are in use ({percent}%).'),

('PG-CAP-001', 'tr', 'FINDING', '{node_name} üzerindeki veri diski {mount_point} %{used_percent} dolu (data_directory: {data_directory}).'),
('PG-CAP-001', 'en', 'FINDING', 'The data disk {mount_point} on {node_name} is {used_percent}% full (data_directory {data_directory}).'),

('PG-CONF-001', 'tr', 'FINDING', '{node_name} üzerinde {setting} ayarı değiştirilmiş ve restart bekliyor (geçerli değer: {value}).'),
('PG-CONF-001', 'en', 'FINDING', 'Setting {setting} on {node_name} was changed and waits for a restart (running value: {value}).'),
('PG-CONF-002', 'tr', 'FINDING', '{node_name} üzerinde {setting} = {value}.'),
('PG-CONF-002', 'en', 'FINDING', 'Setting {setting} is {value} on {node_name}.'),
('PG-CONF-004', 'tr', 'FINDING', '{node_name} üzerinde {setting} = {value}; autovacuum çalışmıyor.'),
('PG-CONF-004', 'en', 'FINDING', 'Setting {setting} is {value} on {node_name}; autovacuum does not run.'),

('PG-BKP-002', 'tr', 'FINDING', '{node_name} üzerinde {setting} = {value}; WAL arşivlenmiyor.'),
('PG-BKP-002', 'en', 'FINDING', 'Setting {setting} is {value} on {node_name}; WAL is not archived.'),
('PG-BKP-002', 'tr', 'FINDING_ALT', '{node_name} üzerinde archive_mode = {archive_mode} ama archive_command ve archive_library boş; WAL dosyaları birikiyor.'),
('PG-BKP-002', 'en', 'FINDING_ALT', 'archive_mode is {archive_mode} on {node_name} but archive_command and archive_library are empty; WAL files accumulate.'),

('PG-SEC-002', 'tr', 'FINDING', '{node_name} üzerinde {setting} = {value}.'),
('PG-SEC-002', 'en', 'FINDING', 'Setting {setting} is {value} on {node_name}.'),
('PG-SEC-003', 'tr', 'FINDING', '{node_name} üzerinde {setting} = {value}.'),
('PG-SEC-003', 'en', 'FINDING', 'Setting {setting} is {value} on {node_name}.'),

('PG-MAINT-001', 'tr', 'FINDING', '{table} tablosunda {dead_rows} dead tuple var (tüm satırların %{percent} kadarı).'),
('PG-MAINT-001', 'en', 'FINDING', 'Table {table} has {dead_rows} dead rows ({percent}% of all rows).'),
('PG-MAINT-002', 'tr', 'FINDING', '{table} tablosunda son ANALYZE''dan beri {modified_rows} satır değişmiş (canlı satırların %{percent} kadarı).'),
('PG-MAINT-002', 'en', 'FINDING', 'Table {table} has {modified_rows} rows changed since its last analyze ({percent}% of live rows).')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
