/*
===============================================================================
Migration No : 034
Version      : V034
Title        : Rule Texts: Causes and Steps

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the CAUSES rule text type. MEANING becomes "what is happening" only;
CAUSES and RECOMMENDATION are lists, one item per line starting with "- ".
Rewrites the texts of all rules in Turkish and English.
===============================================================================
*/


/*
Design notes (2026-10-21, report review)
----------------------------------------
Problem cards listed several independent causes and steps in one sentence and
labelled "what is happening" as "likely cause". Cards now show: what is
happening (one sentence), likely causes (list), why it matters, what to do
(steps). List items stay short; reports render them as bullets.
===============================================================================
*/

ALTER TABLE keystone.rule_text DROP CONSTRAINT ck_rule_text_type;

ALTER TABLE keystone.rule_text
    ADD CONSTRAINT ck_rule_text_type
    CHECK (text_type IN ('NAME', 'HEALTHY', 'MEANING', 'CAUSES', 'IMPACT', 'RECOMMENDATION'));

COMMENT ON COLUMN keystone.rule_text.text IS
'Plain text. CAUSES and RECOMMENDATION are lists: one item per line, each starting with "- ".';


INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-TRAN-001 ---------------------------------------------------------------
('PG-TRAN-001', 'tr', 'MEANING',
 'Bazı session''lar bir transaction başlatmış ama ne commit ne de rollback ediyor; veritabanıyla konuşmayı bırakmış durumdalar.'),
('PG-TRAN-001', 'tr', 'CAUSES', E'- Uygulama bir hatadan sonra transaction''ı kapatmıyor\n- Transaction açıkken başka bir iş yapılıyor (dış servis çağrısı, kullanıcı girdisi beklemek)\n- Connection pool session''ı bırakmıyor'),
('PG-TRAN-001', 'tr', 'RECOMMENDATION', E'- Session''ın hangi uygulamaya ait olduğunu bulun (teknik detaylarda uygulama, kullanıcı ve istemci adresi var)\n- Transaction''ın neden açık kaldığını uygulama koduyla birlikte inceleyin\n- Uygulamanın hata durumunda da transaction''ları kapattığından emin olun\n- Gerekirse idle_in_transaction_session_timeout ile bir üst sınır tanımlayın'),
('PG-TRAN-001', 'en', 'MEANING',
 'Some sessions started a transaction but neither commit nor roll back; they have stopped talking to the database.'),
('PG-TRAN-001', 'en', 'CAUSES', E'- The application does not close the transaction after an error\n- Other work is done while the transaction is open (calling an external service, waiting for user input)\n- The connection pool does not release the session'),
('PG-TRAN-001', 'en', 'RECOMMENDATION', E'- Find the application that owns the session (the technical details show application, user and client address)\n- Review with the application code why the transaction stays open\n- Make sure the application closes transactions on errors too\n- If needed, set an upper limit with idle_in_transaction_session_timeout'),

-- PG-TRAN-003 ---------------------------------------------------------------
('PG-TRAN-003', 'tr', 'MEANING',
 'Bir transaction tanımlı eşikten daha uzun süredir açık.'),
('PG-TRAN-003', 'tr', 'CAUSES', E'- Planlı bir toplu iş ya da veri yükleme\n- Uzun süren bir rapor ya da analiz sorgusu\n- Yedekleme (pg_dump)\n- Uygulamanın transaction''ı gereğinden uzun tutması'),
('PG-TRAN-003', 'tr', 'RECOMMENDATION', E'- Transaction''ın hangi işe ait olduğunu belirleyin\n- Planlı bir işse yoğun saatlerin dışına alın ya da daha küçük transaction''lara bölün\n- Planlı değilse uygulamanın transaction sınırlarını gözden geçirin'),
('PG-TRAN-003', 'en', 'MEANING',
 'A transaction has been open longer than the configured limit.'),
('PG-TRAN-003', 'en', 'CAUSES', E'- A planned batch job or data load\n- A long report or analysis query\n- A backup (pg_dump)\n- The application keeps the transaction open longer than needed'),
('PG-TRAN-003', 'en', 'RECOMMENDATION', E'- Identify the work behind the transaction\n- If it is planned work, move it out of busy hours or split it into smaller transactions\n- Otherwise review the application''s transaction boundaries'),

-- PG-TRAN-002 ---------------------------------------------------------------
('PG-TRAN-002', 'tr', 'MEANING',
 'PostgreSQL her transaction''a bir numara verir ve bu sayaç yaklaşık 2 milyarda başa döner; bunun güvenli olması için vacuum eski kayıtları düzenli olarak freeze etmelidir. Bu veritabanında freeze geride kalmış ve sayaç sınıra yaklaşıyor.'),
('PG-TRAN-002', 'tr', 'CAUSES', E'- Autovacuum yetişemiyor ya da kapatılmış\n- Freeze edilmesi uzun süren çok büyük tablolar\n- Vacuum''u engelleyen uzun transaction''lar ya da replication slot''lar'),
('PG-TRAN-002', 'tr', 'RECOMMENDATION', E'- Autovacuum''un bu veritabanında çalıştığını doğrulayın\n- Hangi tabloların geride kaldığını belirleyin (age(relfrozenxid))\n- Planlı bir VACUUM (FREEZE) çalıştırın\n- Vacuum''u engelleyen uzun transaction''ları ve kullanılmayan slot''ları giderin'),
('PG-TRAN-002', 'en', 'MEANING',
 'PostgreSQL numbers every transaction and the counter wraps around at about 2 billion; to stay safe, vacuum must freeze old rows regularly. In this database freezing has fallen behind and the counter is approaching the limit.'),
('PG-TRAN-002', 'en', 'CAUSES', E'- Autovacuum is not keeping up or is disabled\n- Very large tables that take long to freeze\n- Long transactions or replication slots blocking vacuum'),
('PG-TRAN-002', 'en', 'RECOMMENDATION', E'- Verify that autovacuum runs in this database\n- Find the tables that are behind (age(relfrozenxid))\n- Run a planned VACUUM (FREEZE)\n- Resolve long transactions and unused slots that block vacuum'),

-- PG-REP-001 ----------------------------------------------------------------
('PG-REP-001', 'tr', 'MEANING',
 'Bir replication slot''un tüketicisi değişiklikleri yeterince hızlı almıyor; primary onun için WAL''ı normal sınırın (max_wal_size) üzerinde saklıyor.'),
('PG-REP-001', 'tr', 'CAUSES', E'- Replica yavaş, kapalı ya da ağdan kopmuş\n- Slot''u kullanan veri aktarım aracı (CDC, logical replication) durmuş\n- Artık kullanılmayan ama silinmemiş bir slot'),
('PG-REP-001', 'tr', 'RECOMMENDATION', E'- Slot''u kullanan replica ya da aracın çalıştığını ve ilerlediğini doğrulayın\n- Slot kullanılmıyorsa kaldırılmasını değerlendirin\n- Primary''deki disk alanını takip edin'),
('PG-REP-001', 'en', 'MEANING',
 'The consumer of a replication slot is not taking changes fast enough; the primary keeps WAL for it beyond the normal limit (max_wal_size).'),
('PG-REP-001', 'en', 'CAUSES', E'- The replica is slow, down or disconnected\n- The data transfer tool using the slot (CDC, logical replication) has stopped\n- A slot that is no longer used was not dropped'),
('PG-REP-001', 'en', 'RECOMMENDATION', E'- Verify that the replica or tool using the slot is running and making progress\n- If the slot is not used, consider dropping it\n- Watch disk space on the primary'),

-- PG-REP-002 ----------------------------------------------------------------
('PG-REP-002', 'tr', 'MEANING',
 'Bir replica ya da veri aktarım aracının ihtiyaç duyduğu WAL artık korunmuyor (unreserved) ya da silinmiş (lost).'),
('PG-REP-002', 'tr', 'CAUSES', E'- Tüketici çok uzun süre kapalı kaldı ya da geride kaldı\n- max_slot_wal_keep_size sınırı aşıldı'),
('PG-REP-002', 'tr', 'RECOMMENDATION', E'- Tüketiciyi acilen inceleyin\n- WAL henüz silinmediyse (unreserved) tüketiciyi hızla devreye alın\n- WAL silindiyse (lost) replica ya da slot yeniden kurulmalı'),
('PG-REP-002', 'en', 'MEANING',
 'WAL that a replica or data transfer tool needs is no longer retained (unreserved) or already removed (lost).'),
('PG-REP-002', 'en', 'CAUSES', E'- The consumer was down or behind for too long\n- The max_slot_wal_keep_size limit was exceeded'),
('PG-REP-002', 'en', 'RECOMMENDATION', E'- Investigate the consumer immediately\n- If WAL is not removed yet (unreserved), bring the consumer back quickly\n- If WAL was removed (lost), the replica or slot must be rebuilt'),

-- PG-REP-003 ----------------------------------------------------------------
('PG-REP-003', 'tr', 'MEANING',
 'Replica, primary''de yapılan değişiklikleri geriden uyguluyor.'),
('PG-REP-003', 'tr', 'CAUSES', E'- Primary''de yoğun yazma yükü\n- Ağ yavaşlığı ya da yetersiz bant genişliği\n- Replica''nın disk ya da CPU kaynağının yetersiz olması\n- Replica''da uzun süren sorguların değişikliklerin uygulanmasını bekletmesi'),
('PG-REP-003', 'tr', 'RECOMMENDATION', E'- Gecikmenin nereden geldiğini ayırın: write/flush gecikmesi ağı ya da replica''nın diskini, yalnızca replay gecikmesi replica''daki yükü gösterir\n- Replica''nın kaynaklarını (disk, CPU) primary ile karşılaştırın\n- Replica''daki uzun sorguları ve hot_standby_feedback / max_standby_streaming_delay ayarlarını gözden geçirin'),
('PG-REP-003', 'en', 'MEANING',
 'A replica applies the primary''s changes late.'),
('PG-REP-003', 'en', 'CAUSES', E'- Heavy write load on the primary\n- A slow network or too little bandwidth\n- Too little disk or CPU on the replica\n- Long queries on the replica holding back replay'),
('PG-REP-003', 'en', 'RECOMMENDATION', E'- Separate where the lag comes from: write/flush lag points to the network or the replica''s disk, replay lag alone to load on the replica\n- Compare the replica''s resources (disk, CPU) with the primary''s\n- Review long queries on the replica and hot_standby_feedback / max_standby_streaming_delay'),

-- PG-REP-004 ----------------------------------------------------------------
('PG-REP-004', 'tr', 'MEANING',
 'Replica olarak bilinen bir sunucu primary''den değişiklik almıyor.'),
('PG-REP-004', 'tr', 'CAUSES', E'- Sunucu ya da PostgreSQL servisi kapalı\n- Primary''ye ağ üzerinden ulaşamıyor\n- Replikasyon bağlantısı kopmuş ya da kimlik doğrulaması başarısız\n- Hâlâ başlangıç ya da yakalama aşamasında'),
('PG-REP-004', 'tr', 'RECOMMENDATION', E'- Replica sunucusunun ve PostgreSQL servisinin çalıştığını kontrol edin\n- Primary''ye ağ erişimini doğrulayın\n- Replica''nın PostgreSQL loglarındaki replikasyon hatalarını inceleyin\n- Patroni gibi bir HA aracı varsa durumunu inceleyin (patronictl list)'),
('PG-REP-004', 'en', 'MEANING',
 'A server known as a replica is not receiving changes from the primary.'),
('PG-REP-004', 'en', 'CAUSES', E'- The server or the PostgreSQL service is down\n- It cannot reach the primary over the network\n- The replication connection broke or authentication fails\n- It is still starting up or catching up'),
('PG-REP-004', 'en', 'RECOMMENDATION', E'- Check that the replica server and the PostgreSQL service are running\n- Verify network access to the primary\n- Review replication errors in the replica''s PostgreSQL logs\n- If an HA tool such as Patroni is used, review its state (patronictl list)'),

-- PG-REP-005 ----------------------------------------------------------------
('PG-REP-005', 'tr', 'MEANING',
 'Bir replication slot tanımlı ama şu anda ona bağlı bir tüketici yok.'),
('PG-REP-005', 'tr', 'CAUSES', E'- Slot''un replica''sı kapalı ya da kaldırılmış\n- Silinmemiş bir logical replication aboneliği\n- Durmuş bir veri aktarım (CDC) aracı'),
('PG-REP-005', 'tr', 'RECOMMENDATION', E'- Slot''un kime ait olduğunu belirleyin\n- Tüketicisi geri gelmeyecekse slot''u silin (pg_drop_replication_slot)\n- Geri gelecekse biriken WAL''ı izleyin\n- max_slot_wal_keep_size ile bir üst sınır tanımlayın'),
('PG-REP-005', 'en', 'MEANING',
 'A replication slot exists but no consumer is connected to it.'),
('PG-REP-005', 'en', 'CAUSES', E'- The slot''s replica is down or was removed\n- A logical replication subscription was not dropped\n- A data transfer (CDC) tool has stopped'),
('PG-REP-005', 'en', 'RECOMMENDATION', E'- Identify who owns the slot\n- If its consumer will not come back, drop the slot (pg_drop_replication_slot)\n- If it will, watch the retained WAL\n- Set an upper limit with max_slot_wal_keep_size'),

-- PG-REP-006 ----------------------------------------------------------------
('PG-REP-006', 'tr', 'MEANING',
 'Primary''de synchronous replikasyon tanımlı, ama şu anda synchronous durumda olan bir standby yok.'),
('PG-REP-006', 'tr', 'CAUSES', E'- Synchronous standby kapalı ya da bağlantısı kopmuş\n- synchronous_standby_names içindeki ad, standby''ların application_name değeriyle eşleşmiyor\n- HA aracı standby olmasa da synchronous replikasyonu zorunlu tutuyor (Patroni synchronous_mode_strict)'),
('PG-REP-006', 'tr', 'RECOMMENDATION', E'- Standby''ların neden bağlı olmadığını giderin\n- synchronous_standby_names değerini standby''ların application_name değerleriyle karşılaştırın\n- Acil durumda synchronous_standby_names boşaltılarak yazma açılabilir; bu, veri güvenliği garantisini geçici olarak kaldırır\n- Patroni kullanılıyorsa synchronous_mode ayarlarını kontrol edin'),
('PG-REP-006', 'en', 'MEANING',
 'Synchronous replication is configured on the primary but no standby is currently synchronous.'),
('PG-REP-006', 'en', 'CAUSES', E'- The synchronous standby is down or disconnected\n- The name in synchronous_standby_names does not match the standbys'' application_name\n- The HA tool enforces synchronous replication even without a standby (Patroni synchronous_mode_strict)'),
('PG-REP-006', 'en', 'RECOMMENDATION', E'- Find out why the standbys are not connected\n- Compare synchronous_standby_names with the standbys'' application_name values\n- In an emergency, emptying synchronous_standby_names lets writes continue; this temporarily removes the durability guarantee\n- With Patroni, check the synchronous_mode settings'),

-- PG-CONN-001 ---------------------------------------------------------------
('PG-CONN-001', 'tr', 'MEANING',
 'Bazı session''larda bir transaction hata almış ama rollback edilmemiş; session rollback edilene kadar kullanılamaz durumda.'),
('PG-CONN-001', 'tr', 'CAUSES', E'- Uygulama hatayı yakalıyor ama transaction''ı kapatmıyor\n- Connection pool, bağlantıyı geri alırken açık transaction''ı temizlemiyor'),
('PG-CONN-001', 'tr', 'RECOMMENDATION', E'- Uygulamanın hata yakalayan kodunda transaction''ların rollback edildiğinden emin olun\n- Connection pool''un bağlantıyı geri alırken transaction''ı sıfırladığını kontrol edin'),
('PG-CONN-001', 'en', 'MEANING',
 'In some sessions a transaction failed but was not rolled back; the session is unusable until rollback.'),
('PG-CONN-001', 'en', 'CAUSES', E'- The application catches the error but does not close the transaction\n- The connection pool does not clean up an open transaction when a connection is returned'),
('PG-CONN-001', 'en', 'RECOMMENDATION', E'- Make sure the application''s error handling rolls back transactions\n- Check that the connection pool resets the transaction when a connection is returned'),

-- PG-CAP-001 ----------------------------------------------------------------
('PG-CAP-001', 'tr', 'MEANING',
 'PostgreSQL''in veri dizininin (data_directory) bulunduğu disk dolmaya yaklaşıyor.'),
('PG-CAP-001', 'tr', 'CAUSES', E'- Veritabanının büyümesi\n- Temizlenmeyen şişkinlik (bloat)\n- Biriken WAL dosyaları (gecikmiş replica, kullanılmayan slot, başarısız WAL arşivleme)\n- Aynı diskte tutulan log ve yedek dosyaları'),
('PG-CAP-001', 'tr', 'RECOMMENDATION', E'- Diskte yer kaplayanları belirleyin: veritabanı ve tablo boyutları, pg_wal dizini, log ve yedek dosyaları\n- Kısa vadede gereksiz dosyaları temizleyin\n- Replication slot''larının WAL biriktirmediğini kontrol edin\n- Büyüme sürüyorsa disk kapasitesini artırmayı planlayın'),
('PG-CAP-001', 'en', 'MEANING',
 'The disk holding PostgreSQL''s data directory (data_directory) is filling up.'),
('PG-CAP-001', 'en', 'CAUSES', E'- Database growth\n- Bloat that is not cleaned up\n- Accumulating WAL files (a lagging replica, an unused slot, failing WAL archiving)\n- Log and backup files kept on the same disk'),
('PG-CAP-001', 'en', 'RECOMMENDATION', E'- Find what uses the space: database and table sizes, the pg_wal directory, log and backup files\n- Remove what is not needed in the short term\n- Check that no replication slot is retaining WAL\n- Plan more capacity if growth continues')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO UPDATE SET text = EXCLUDED.text;
