/*
===============================================================================
Migration No : 029
Version      : V029
Title        : Dictionary Topics, Impact Categories and Rule Texts

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Extends the Keystone Dictionary with provider-independent topics and impact
categories, plain-language rule texts per language (Turkish, English), and
finding.details for the context of a finding (who / where). Seeds the six
current rules.
===============================================================================
*/


/*
Design notes (Reference Architecture: Keystone Dictionary; 2026-10-19)
----------------------------------------------------------------------
Topic: WHERE a problem is (replication, transactions...). Groups rules in the
technical part of the report. Generic engineering concept, shared by
providers.

Impact category: WHAT a problem affects (availability, performance,
capacity, data safety, security). A rule may have several. Feeds the
executive part of the report.

Rule texts, per language:
  NAME            short rule name
  HEALTHY         what "no finding" means, in plain words
  MEANING         what a finding means and its usual causes
  IMPACT          what happens if it is not handled
  RECOMMENDATION  what to do

Established technical terms (transaction, session, lock, vacuum, WAL,
replica, replication slot, primary, rollback, connection pool) are kept in
English in every language.

Causes in MEANING are typical causes, not the root cause of a specific
system; evidence-based root cause analysis is a later step.

Adding a language = adding a dictionary_language row and its texts.
===============================================================================
*/


/* ============================================================================
   LANGUAGES
   ============================================================================ */

CREATE TABLE keystone.dictionary_language
(
    language_code  VARCHAR(10)  NOT NULL,
    name           VARCHAR(50)  NOT NULL,

    CONSTRAINT pk_dictionary_language PRIMARY KEY (language_code)
);

INSERT INTO keystone.dictionary_language (language_code, name) VALUES
    ('tr', 'Türkçe'),
    ('en', 'English');


/* ============================================================================
   TOPICS
   ============================================================================ */

CREATE TABLE keystone.dictionary_topic
(
    topic_key      VARCHAR(50)  NOT NULL,
    display_order  SMALLINT     NOT NULL,

    CONSTRAINT pk_dictionary_topic PRIMARY KEY (topic_key)
);

CREATE TABLE keystone.dictionary_topic_text
(
    topic_key      VARCHAR(50)  NOT NULL,
    language_code  VARCHAR(10)  NOT NULL,
    name           VARCHAR(100) NOT NULL,
    healthy_text   TEXT         NOT NULL,

    CONSTRAINT pk_dictionary_topic_text PRIMARY KEY (topic_key, language_code),
    CONSTRAINT fk_dictionary_topic_text_topic
        FOREIGN KEY (topic_key) REFERENCES keystone.dictionary_topic (topic_key),
    CONSTRAINT fk_dictionary_topic_text_language
        FOREIGN KEY (language_code) REFERENCES keystone.dictionary_language (language_code)
);

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('TRANSACTIONS', 10),
    ('MAINTENANCE',  20),
    ('REPLICATION',  30),
    ('CONNECTIONS',  40);

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name, healthy_text) VALUES
    ('TRANSACTIONS', 'tr', 'Transaction yönetimi',
     'Sistemi bloklayan ya da uzun süre açık kalan transaction yok.'),
    ('TRANSACTIONS', 'en', 'Transaction management',
     'No transaction is blocking the system or has been open for long.'),
    ('MAINTENANCE',  'tr', 'Veritabanı bakımı',
     'Vacuum düzenli çalışıyor; transaction ID sayacı güvenli seviyede.'),
    ('MAINTENANCE',  'en', 'Database maintenance',
     'Vacuum keeps up; the transaction ID counter is at a safe level.'),
    ('REPLICATION',  'tr', 'Replikasyon',
     'Replikasyonda sorun yok; replica''lar beslenmeye devam ediyor.'),
    ('REPLICATION',  'en', 'Replication',
     'Replication is fine; replicas keep receiving changes.'),
    ('CONNECTIONS',  'tr', 'Bağlantılar',
     'Hata alıp kapatılmamış session yok.'),
    ('CONNECTIONS',  'en', 'Connections',
     'No session is left in a failed, unclosed transaction.');


/* ============================================================================
   IMPACT CATEGORIES
   ============================================================================ */

CREATE TABLE keystone.dictionary_impact_category
(
    category_key   VARCHAR(50)  NOT NULL,
    display_order  SMALLINT     NOT NULL,

    CONSTRAINT pk_dictionary_impact_category PRIMARY KEY (category_key)
);

CREATE TABLE keystone.dictionary_impact_category_text
(
    category_key   VARCHAR(50)  NOT NULL,
    language_code  VARCHAR(10)  NOT NULL,
    name           VARCHAR(100) NOT NULL,
    description    TEXT         NOT NULL,

    CONSTRAINT pk_dictionary_impact_category_text PRIMARY KEY (category_key, language_code),
    CONSTRAINT fk_dictionary_impact_category_text_category
        FOREIGN KEY (category_key) REFERENCES keystone.dictionary_impact_category (category_key),
    CONSTRAINT fk_dictionary_impact_category_text_language
        FOREIGN KEY (language_code) REFERENCES keystone.dictionary_language (language_code)
);

INSERT INTO keystone.dictionary_impact_category (category_key, display_order) VALUES
    ('AVAILABILITY', 10),
    ('PERFORMANCE',  20),
    ('CAPACITY',     30),
    ('DATA_SAFETY',  40),
    ('SECURITY',     50);

INSERT INTO keystone.dictionary_impact_category_text (category_key, language_code, name, description) VALUES
    ('AVAILABILITY', 'tr', 'Erişilebilirlik', 'Sistem durabilir ya da yazamaz hale gelebilir.'),
    ('AVAILABILITY', 'en', 'Availability',    'The system may stop or become unable to write.'),
    ('PERFORMANCE',  'tr', 'Performans',      'Yavaşlama ve bekleme.'),
    ('PERFORMANCE',  'en', 'Performance',     'Slowdowns and waiting.'),
    ('CAPACITY',     'tr', 'Kapasite',        'Disk, bağlantı ya da kaynak tükenmesi.'),
    ('CAPACITY',     'en', 'Capacity',        'Running out of disk, connections or resources.'),
    ('DATA_SAFETY',  'tr', 'Veri güvenliği',  'Veri kaybı ya da tutarsızlık riski.'),
    ('DATA_SAFETY',  'en', 'Data safety',     'Risk of data loss or inconsistency.'),
    ('SECURITY',     'tr', 'Güvenlik',        'Yetki ve erişim.'),
    ('SECURITY',     'en', 'Security',        'Permissions and access.');


/* ============================================================================
   RULES: TOPIC AND IMPACT CATEGORIES
   ============================================================================ */

ALTER TABLE keystone.rule_definition
    ADD COLUMN topic_key VARCHAR(50);

ALTER TABLE keystone.rule_definition
    ADD CONSTRAINT fk_rule_definition_topic
        FOREIGN KEY (topic_key) REFERENCES keystone.dictionary_topic (topic_key);

COMMENT ON COLUMN keystone.rule_definition.topic_key IS
'Provider-independent topic the rule belongs to (where the problem is).';

UPDATE keystone.rule_definition SET topic_key = 'TRANSACTIONS' WHERE rule_key IN ('PG-TRAN-001', 'PG-TRAN-003');
UPDATE keystone.rule_definition SET topic_key = 'MAINTENANCE'  WHERE rule_key = 'PG-TRAN-002';
UPDATE keystone.rule_definition SET topic_key = 'REPLICATION'  WHERE rule_key IN ('PG-REP-001', 'PG-REP-002');
UPDATE keystone.rule_definition SET topic_key = 'CONNECTIONS'  WHERE rule_key = 'PG-CONN-001';

CREATE TABLE keystone.rule_impact_category
(
    rule_id        BIGINT       NOT NULL,
    category_key   VARCHAR(50)  NOT NULL,

    CONSTRAINT pk_rule_impact_category PRIMARY KEY (rule_id, category_key),
    CONSTRAINT fk_rule_impact_category_rule
        FOREIGN KEY (rule_id) REFERENCES keystone.rule_definition (rule_id),
    CONSTRAINT fk_rule_impact_category_category
        FOREIGN KEY (category_key) REFERENCES keystone.dictionary_impact_category (category_key)
);

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-TRAN-001', 'PERFORMANCE'),
    ('PG-TRAN-001', 'CAPACITY'),
    ('PG-TRAN-003', 'PERFORMANCE'),
    ('PG-TRAN-003', 'CAPACITY'),
    ('PG-TRAN-002', 'AVAILABILITY'),
    ('PG-REP-001',  'CAPACITY'),
    ('PG-REP-001',  'AVAILABILITY'),
    ('PG-REP-002',  'AVAILABILITY'),
    ('PG-REP-002',  'DATA_SAFETY'),
    ('PG-CONN-001', 'CAPACITY'),
    ('PG-CONN-001', 'AVAILABILITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key;


/* ============================================================================
   RULE TEXTS
   ============================================================================ */

CREATE TABLE keystone.rule_text
(
    rule_id        BIGINT       NOT NULL,
    language_code  VARCHAR(10)  NOT NULL,
    text_type      VARCHAR(20)  NOT NULL,
    text           TEXT         NOT NULL,

    CONSTRAINT pk_rule_text PRIMARY KEY (rule_id, language_code, text_type),
    CONSTRAINT fk_rule_text_rule
        FOREIGN KEY (rule_id) REFERENCES keystone.rule_definition (rule_id),
    CONSTRAINT fk_rule_text_language
        FOREIGN KEY (language_code) REFERENCES keystone.dictionary_language (language_code),
    CONSTRAINT ck_rule_text_type
        CHECK (text_type IN ('NAME', 'HEALTHY', 'MEANING', 'IMPACT', 'RECOMMENDATION'))
);

COMMENT ON TABLE keystone.rule_text IS
'Plain-language texts of a rule per language, for reports and the user interface.';

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES

-- PG-TRAN-001 ---------------------------------------------------------------
('PG-TRAN-001', 'tr', 'NAME', 'Uzun süre boşta bekleyen transaction'),
('PG-TRAN-001', 'tr', 'HEALTHY',
 'Transaction açıp tamamlamadan bekleyen session yok; uygulamalar transaction''larını düzgün kapatıyor.'),
('PG-TRAN-001', 'tr', 'MEANING',
 'Bazı session''lar bir transaction başlatmış ama ne commit ne de rollback ediyor; veritabanıyla konuşmayı bırakmış durumdalar. Bu genellikle şunlardan birine işaret eder: uygulama bir hatadan sonra transaction''ı kapatmıyor, transaction açıkken başka bir işe geçiliyor (ör. dış servis çağrısı ya da kullanıcı girdisi beklemek) veya connection pool session''ı bırakmıyor.'),
('PG-TRAN-001', 'tr', 'IMPACT',
 'Açık transaction''ın tuttuğu lock''lar aynı verilere erişmek isteyen diğer işlemleri bekletebilir; bu, uygulamada yavaşlama ya da zaman aşımı olarak görünür. Ayrıca vacuum''u engeller: tablolar şişer, disk kullanımı artar, sorgular zamanla yavaşlar.'),
('PG-TRAN-001', 'tr', 'RECOMMENDATION',
 'Session''ın hangi uygulamaya ait olduğunu bulun ve transaction''ın neden açık kaldığını inceleyin. Uygulamanın hata durumunda da transaction''ları kapattığından emin olun. Gerekirse idle_in_transaction_session_timeout ile bir üst sınır tanımlanabilir.'),
('PG-TRAN-001', 'en', 'NAME', 'Long idle transaction'),
('PG-TRAN-001', 'en', 'HEALTHY',
 'No session keeps a transaction open without finishing it; applications close their transactions properly.'),
('PG-TRAN-001', 'en', 'MEANING',
 'Some sessions started a transaction but neither commit nor roll back; they have stopped talking to the database. This usually points to one of these: the application does not close the transaction after an error, other work is done while the transaction is open (for example calling an external service or waiting for user input), or the connection pool does not release the session.'),
('PG-TRAN-001', 'en', 'IMPACT',
 'Locks held by the open transaction can make other work on the same data wait; the application sees this as slowness or timeouts. It also blocks vacuum: tables bloat, disk usage grows and queries slow down over time.'),
('PG-TRAN-001', 'en', 'RECOMMENDATION',
 'Find the application that owns the session and why the transaction stays open. Make sure the application closes transactions on errors too. If needed, idle_in_transaction_session_timeout can set an upper limit.'),

-- PG-TRAN-003 ---------------------------------------------------------------
('PG-TRAN-003', 'tr', 'NAME', 'Uzun süren transaction'),
('PG-TRAN-003', 'tr', 'HEALTHY',
 'Uzun süredir açık olan transaction yok; vacuum engellenmiyor.'),
('PG-TRAN-003', 'tr', 'MEANING',
 'Bir transaction 30 dakikadan uzun süredir açık. Bu bir toplu iş, uzun bir rapor sorgusu ya da yedekleme (pg_dump) olabilir; uygulamanın transaction''ı gereğinden uzun tutması da olabilir.'),
('PG-TRAN-003', 'tr', 'IMPACT',
 'Transaction açık kaldıkça, o andan sonra değişen kayıtların eski sürümleri vacuum tarafından temizlenemez: tablolar ve indeksler şişer, disk kullanımı artar, performans düşer. Transaction''ın tuttuğu lock''lar başka işlemleri bekletebilir.'),
('PG-TRAN-003', 'tr', 'RECOMMENDATION',
 'Transaction''ın hangi işe ait olduğunu belirleyin. Planlı bir toplu işse yoğun saatlerin dışına alınmasını ya da daha küçük transaction''lara bölünmesini değerlendirin; değilse uygulamanın transaction sınırlarını gözden geçirin.'),
('PG-TRAN-003', 'en', 'NAME', 'Long-running transaction'),
('PG-TRAN-003', 'en', 'HEALTHY',
 'No transaction has been open for long; vacuum is not held back.'),
('PG-TRAN-003', 'en', 'MEANING',
 'A transaction has been open for more than 30 minutes. It may be a batch job, a long report query or a backup (pg_dump), or the application may keep the transaction open longer than needed.'),
('PG-TRAN-003', 'en', 'IMPACT',
 'While the transaction stays open, vacuum cannot remove old versions of rows changed since it started: tables and indexes bloat, disk usage grows and performance drops. Locks held by the transaction can make other work wait.'),
('PG-TRAN-003', 'en', 'RECOMMENDATION',
 'Identify the work behind the transaction. If it is a planned batch job, consider moving it out of busy hours or splitting it into smaller transactions; otherwise review the application''s transaction boundaries.'),

-- PG-TRAN-002 ---------------------------------------------------------------
('PG-TRAN-002', 'tr', 'NAME', 'Transaction ID wraparound riski'),
('PG-TRAN-002', 'tr', 'HEALTHY',
 'Veritabanlarının transaction ID sayacı güvenli seviyede; vacuum eski kayıtları düzenli olarak freeze ediyor.'),
('PG-TRAN-002', 'tr', 'MEANING',
 'PostgreSQL her transaction''a bir numara (transaction ID) verir ve bu sayaç yaklaşık 2 milyarda başa döner. Sayacın güvenle ilerleyebilmesi için vacuum''un eski kayıtları düzenli olarak freeze etmesi gerekir. Bu veritabanında freeze geride kalmış ve sayaç sınıra yaklaşıyor. Sebep genellikle autovacuum''un yetişememesi, çok büyük tablolar ya da vacuum''u engelleyen uzun transaction''lardır.'),
('PG-TRAN-002', 'tr', 'IMPACT',
 'Sınıra ulaşılırsa PostgreSQL, veri bozulmasını önlemek için yeni yazma işlemlerini kabul etmez ve uygulamalar veritabanına yazamaz hale gelir. Bu durumdan çıkmak saatler süren bir bakım gerektirebilir.'),
('PG-TRAN-002', 'tr', 'RECOMMENDATION',
 'Autovacuum''un bu veritabanında çalışıp çalışmadığını ve hangi tabloların geride kaldığını inceleyin. Gerekirse planlı bir VACUUM (FREEZE) çalıştırın ve vacuum''u engelleyen uzun transaction''ları giderin.'),
('PG-TRAN-002', 'en', 'NAME', 'Transaction ID wraparound risk'),
('PG-TRAN-002', 'en', 'HEALTHY',
 'The transaction ID counter of the databases is at a safe level; vacuum freezes old rows regularly.'),
('PG-TRAN-002', 'en', 'MEANING',
 'PostgreSQL numbers every transaction (transaction ID) and the counter wraps around at about 2 billion. To advance safely, vacuum must freeze old rows regularly. In this database freezing has fallen behind and the counter is approaching the limit. Usual causes are autovacuum not keeping up, very large tables or long transactions blocking vacuum.'),
('PG-TRAN-002', 'en', 'IMPACT',
 'If the limit is reached, PostgreSQL stops accepting new writes to prevent data corruption and applications can no longer write to the database. Recovering can take hours of maintenance.'),
('PG-TRAN-002', 'en', 'RECOMMENDATION',
 'Check whether autovacuum runs in this database and which tables are behind. If needed, run a planned VACUUM (FREEZE) and resolve long transactions that block vacuum.'),

-- PG-REP-001 ----------------------------------------------------------------
('PG-REP-001', 'tr', 'NAME', 'Replication slot''ta WAL birikmesi'),
('PG-REP-001', 'tr', 'HEALTHY',
 'Replication slot''lar değişiklikleri zamanında tüketiyor; birikmiş WAL yok.'),
('PG-REP-001', 'tr', 'MEANING',
 'Bir replica ya da veri aktarım aracı, replication slot üzerinden değişiklikleri yeterince hızlı alamıyor; primary onun için WAL''ı normal sınırın (max_wal_size) üzerinde saklamaya başladı. Replica yavaş, kapalı ya da ağdan kopmuş olabilir; slot''u kullanan araç durmuş olabilir.'),
('PG-REP-001', 'tr', 'IMPACT',
 'WAL birikmeye devam ederse primary''nin diski dolabilir; disk dolarsa veritabanı durur. Replica da güncel veriyi geriden takip ediyor olabilir.'),
('PG-REP-001', 'tr', 'RECOMMENDATION',
 'Slot''u kullanan replica ya da aracın çalıştığını ve ilerlediğini doğrulayın. Slot kullanılmıyorsa kaldırılmasını değerlendirin. Primary''deki disk alanını takip edin.'),
('PG-REP-001', 'en', 'NAME', 'WAL piling up for a replication slot'),
('PG-REP-001', 'en', 'HEALTHY',
 'Replication slots consume changes in time; no WAL is piling up.'),
('PG-REP-001', 'en', 'MEANING',
 'A replica or data transfer tool is not taking changes through its replication slot fast enough, so the primary keeps WAL for it beyond the normal limit (max_wal_size). The replica may be slow, down or disconnected, or the tool using the slot may have stopped.'),
('PG-REP-001', 'en', 'IMPACT',
 'If WAL keeps piling up, the primary''s disk can fill; a full disk stops the database. The replica may also be behind on current data.'),
('PG-REP-001', 'en', 'RECOMMENDATION',
 'Verify that the replica or tool using the slot is running and making progress. If the slot is not used, consider dropping it. Watch disk space on the primary.'),

-- PG-REP-002 ----------------------------------------------------------------
('PG-REP-002', 'tr', 'NAME', 'Replication slot için gereken WAL kaybedildi'),
('PG-REP-002', 'tr', 'HEALTHY',
 'Replication slot''ların ihtiyaç duyduğu WAL korunuyor; replica''lar kaldıkları yerden devam edebilir.'),
('PG-REP-002', 'tr', 'MEANING',
 'Bir replica ya da veri aktarım aracının ihtiyaç duyduğu WAL artık korunmuyor (unreserved) ya da silinmiş (lost). Tüketici çok uzun süre geride kaldığı için primary bu WAL''ı tutmayı bıraktı.'),
('PG-REP-002', 'tr', 'IMPACT',
 'Bu replica ya da araç kaldığı yerden devam edemeyebilir. Replica yüksek erişilebilirlik için kullanılıyorsa, primary arızalandığında devralacak güncel bir kopya olmayabilir; veri aktarımı yapılan bir sistemde veri eksik kalabilir.'),
('PG-REP-002', 'tr', 'RECOMMENDATION',
 'Tüketiciyi acilen inceleyin. WAL silinmişse (lost) replica ya da slot yeniden kurulmalıdır; henüz silinmemişse (unreserved) tüketiciyi hızla devreye alarak kaybı önleyin.'),
('PG-REP-002', 'en', 'NAME', 'WAL needed by a replication slot is lost'),
('PG-REP-002', 'en', 'HEALTHY',
 'WAL needed by replication slots is retained; replicas can continue where they stopped.'),
('PG-REP-002', 'en', 'MEANING',
 'WAL that a replica or data transfer tool needs is no longer retained (unreserved) or already removed (lost). The consumer fell behind for so long that the primary stopped keeping this WAL.'),
('PG-REP-002', 'en', 'IMPACT',
 'This replica or tool may be unable to continue where it stopped. If the replica serves high availability, there may be no up-to-date copy to take over when the primary fails; a downstream system may miss data.'),
('PG-REP-002', 'en', 'RECOMMENDATION',
 'Investigate the consumer immediately. If WAL was removed (lost), the replica or slot must be rebuilt; if it is not removed yet (unreserved), bring the consumer back quickly to prevent the loss.'),

-- PG-CONN-001 ---------------------------------------------------------------
('PG-CONN-001', 'tr', 'NAME', 'Hata alıp kapatılmamış transaction''lar'),
('PG-CONN-001', 'tr', 'HEALTHY',
 'Hata alıp rollback edilmemiş transaction''da bekleyen session yok; uygulamalar hataları düzgün yönetiyor.'),
('PG-CONN-001', 'tr', 'MEANING',
 'Bazı session''larda bir transaction hata almış ama uygulama rollback etmemiş; session rollback edilene kadar kullanılamaz halde bekliyor. Bu, uygulamanın ya da connection pool''un hata yönetiminde bir eksikliğe işaret eder: hata yakalanıyor ama transaction kapatılmıyor.'),
('PG-CONN-001', 'tr', 'IMPACT',
 'Bu session''lar boşuna bağlantı kapasitesi harcar. Connection pool kullanılıyorsa bozuk bağlantı başka bir isteğe verilebilir ve o istek de "current transaction is aborted" hatasıyla başarısız olur; kullanıcılar bunu rastgele hatalar olarak görür.'),
('PG-CONN-001', 'tr', 'RECOMMENDATION',
 'Uygulamanın hata yakalayan kodunda transaction''ların rollback edildiğinden emin olun. Connection pool''un, bir bağlantıyı geri alırken açık transaction''ı temizlediğini kontrol edin.'),
('PG-CONN-001', 'en', 'NAME', 'Failed transactions left open'),
('PG-CONN-001', 'en', 'HEALTHY',
 'No session waits in a failed transaction that was not rolled back; applications handle errors properly.'),
('PG-CONN-001', 'en', 'MEANING',
 'In some sessions a transaction failed but the application did not roll it back; the session is unusable until rollback. This points to a gap in error handling in the application or connection pool: the error is caught but the transaction is not closed.'),
('PG-CONN-001', 'en', 'IMPACT',
 'These sessions waste connection capacity. With a connection pool, the broken connection can be handed to another request, which then fails with "current transaction is aborted"; users see random errors.'),
('PG-CONN-001', 'en', 'RECOMMENDATION',
 'Make sure the application''s error handling rolls back transactions. Check that the connection pool cleans up an open transaction when a connection is returned.')

) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key;


/* ============================================================================
   FINDING CONTEXT
   ============================================================================ */

ALTER TABLE keystone.finding
    ADD COLUMN details JSONB;

COMMENT ON COLUMN keystone.finding.details IS
'Context of the finding from the evidence (e.g. application, user, client address, last query). May contain customer data; shown only in technical reports.';
