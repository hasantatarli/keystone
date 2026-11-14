/*
===============================================================================
Migration No : 062
Version      : V062

Title        : Sequential Scan and Lock Wait Rules
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds PG-IDX-005 Heavy Sequential Scans (PG_INDEX_HEALTH) on the new collector
PG_TABLE_ACCESS over a window of days, and PG-LOCK-001 Lock Waits
(PG_TRANSACTION_HEALTH) on the lock columns added to PG_ACTIVITY_SNAPSHOT
(provider migration PG025).
===============================================================================
*/


/*
Design notes (2026-11-13, Hasan)
--------------------------------
- PG-IDX-005 reads scan counters over a 7-day window (ADR-0020): reports run
  weekly; a single day misleads. Judged: tables of at least 1 GB, at least
  100 sequential scans a day, each reading at least half of the live rows on
  average (a scan stopped by LIMIT is not a full read), sequential scans at
  least 50 % of all scans. A ratio: without history it uses the counters since
  the reset or an unknown start, with the period stated. Sequential scans can
  be right (reports reading most of a table): the texts say "an index may be
  missing", not that one is.
- PG-LOCK-001 is a moment: what waits at collection time, for how long, and
  who blocks it. The wait starts at pg_locks.waitstart (PostgreSQL 14+); before
  14 at the statement's start, and the finding says it is approximate. How
  often locks happen needs frequent collection, not this rule.
- Texts: IMPACT says what happens now and if it goes on; RECOMMENDATION ends
  with what the fix costs.
===============================================================================
*/


/* ============================================================================
   RULE DEFINITIONS
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source, NULL,
       r.finding_template, r.recommendation, r.topic_key
FROM (VALUES
    ('PG_INDEX_HEALTH', 'PG-IDX-005', 'Heavy Sequential Scans',
     'Detects large tables read mostly by sequential scans that each read most of the table.',
     'PG_TABLE_ACCESS',
     'Table {table} in database {database_name} ({size_bytes} bytes) was read by {seq_scans} sequential scans, {share}% of its scans; each read on average {rows_per_scan} of its {live_rows} rows.',
     'Find the queries that scan the table and check whether an index fits their filters.', 'INDEXES'),
    ('PG_TRANSACTION_HEALTH', 'PG-LOCK-001', 'Lock Waits',
     'Detects sessions waiting on a lock for long, and names the sessions blocking them.',
     'PG_ACTIVITY_SNAPSHOT',
     'Session {pid} has been waiting on a lock for {waited_seconds} seconds; blocked by {blockers}.',
     'Find what the blocking session is doing; end its transaction if it is forgotten.', 'TRANSACTIONS')
) AS r (assessment_key, rule_key, name, description, evidence_source, finding_template,
        recommendation, topic_key)
JOIN keystone.assessment_definition ad ON ad.assessment_key = r.assessment_key
ON CONFLICT (rule_key) DO NOTHING;


/* ============================================================================
   THRESHOLDS, PARAMETERS, EVIDENCE, CATEGORIES
   ============================================================================ */

INSERT INTO keystone.rule_threshold (rule_id, severity, threshold_value, threshold_unit)
SELECT rd.rule_id, t.severity, t.threshold_value, t.threshold_unit
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-005',  'WARNING',  50,  'PERCENT'),
    ('PG-LOCK-001', 'WARNING',  30,  'SECOND'),
    ('PG-LOCK-001', 'CRITICAL', 300, 'SECOND')
) AS t (rule_key, severity, threshold_value, threshold_unit) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rd.rule_id, p.parameter_key, p.parameter_value, p.parameter_unit, p.description
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-005', 'window',                604800,     'SECOND', 'Counters are compared with the oldest snapshot within this window.'),
    ('PG-IDX-005', 'min_window',            86400,      'SECOND', 'Statistics younger than this are not judged.'),
    ('PG-IDX-005', 'min_table_size',        1073741824, 'BYTE',   'Smaller tables are not judged.'),
    ('PG-IDX-005', 'min_seq_scans_per_day', 100,        'COUNT',  'Tables scanned sequentially less often are not judged (in the period when its length is unknown).'),
    ('PG-IDX-005', 'min_rows_share',        0.5,        'RATIO',  'A sequential scan must read at least this share of the live rows on average to count as a full read.')
) AS p (rule_key, parameter_key, parameter_value, parameter_unit, description) ON p.rule_key = rd.rule_key
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, e.evidence_source, TRUE, e.max_age_seconds
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-005',  'PG_TABLE_ACCESS',      86400),
    ('PG-LOCK-001', 'PG_ACTIVITY_SNAPSHOT', 600)
) AS e (rule_key, evidence_source, max_age_seconds) ON e.rule_key = rd.rule_key
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-IDX-005',  'PERFORMANCE'),
    ('PG-LOCK-001', 'AVAILABILITY'),
    ('PG-LOCK-001', 'PERFORMANCE')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
-- PG-IDX-005 ------------------------------------------------------------------
('PG-IDX-005', 'tr', 'NAME', 'Ağır sequential scan'),
('PG-IDX-005', 'tr', 'HEALTHY', 'Büyük tablolar çoğunlukla index ile okunuyor; taramaların {warning} veya daha fazlası tam tablo taraması olan büyük tablo yok.'),
('PG-IDX-005', 'tr', 'MEANING', 'Büyük bir tablo çoğunlukla baştan sona taranarak okunuyor ve her tarama tablonun büyük kısmını okuyor. Sorguların filtrelerine uyan bir index eksik olabilir. Kesin hüküm değildir: tablonun çoğunu okuyan rapor sorgularında sequential scan doğru tercihtir.'),
('PG-IDX-005', 'tr', 'CAUSES', E'- Sık çalışan bir sorgunun WHERE ya da JOIN kolonlarında index yok\n- Index var ama sorguya uymuyor: kolon sırası, fonksiyon ya da tip dönüşümü (örneğin lower(email), ::text) index''i kullanılamaz yapıyor\n- Güncel olmayan istatistikler planlayıcıyı tam taramaya yönlendiriyor\n- Tablonun çoğunu okuyan raporlama ya da toplu işler (bu durumda sorun değildir)'),
('PG-IDX-005', 'tr', 'IMPACT', E'Şimdi: her tarama tablonun tamamını diskten ya da bellekten okur; sorgu, index ile milisaniyede bitecekken saniyeler sürer, disk I/O''su ve CPU bütün sistemle paylaşılır.\nBöyle devam ederse: süre tablo büyüklüğüyle orantılı artar; bugün kabul edilebilir olan sorgu tablo büyüdükçe yavaşlar ve önbellekteki başka verinin yerini alır.'),
('PG-IDX-005', 'tr', 'RECOMMENDATION', E'- Tabloyu tarayan sorguları bulun: pg_stat_statements''te tablo adıyla arayın ya da log_min_duration_statement ile yavaş sorguları loglayın\n- Sorgunun planına bakın (EXPLAIN (ANALYZE, BUFFERS)); filtreyle çok az satır dönüyorsa uygun bir index oluşturun: CREATE INDEX CONCURRENTLY ... (tabloyu kilitlemez)\n- Index varsa neden kullanılmadığına bakın: fonksiyonlu ifade, tip dönüşümü, eski istatistik (ANALYZE)\n- Sorgu tablonun çoğunu gerçekten okuyorsa (rapor) bu bulgu kabul edilebilir\n- Bedeli: index oluşturmak disk alanı ister ve yazmaları biraz yavaşlatır; CONCURRENTLY ile kesinti gerekmez.'),
('PG-IDX-005', 'tr', 'FINDING', '{database_name} veritabanındaki {table} tablosu ({size_bytes}) {seq_scans} kez baştan sona tarandı; taramaların %{share} kadarı sequential, her tarama ortalama {rows_per_scan} satır okudu (tabloda {live_rows} satır var).'),
('PG-IDX-005', 'en', 'NAME', 'Heavy sequential scans'),
('PG-IDX-005', 'en', 'HEALTHY', 'Large tables are read mostly through indexes; no large table has {warning} or more of its scans as full table scans.'),
('PG-IDX-005', 'en', 'MEANING', 'A large table is read mostly by scanning it from start to end, and each scan reads most of it. An index matching the queries'' filters may be missing. Not a verdict: for reporting queries that read most of a table a sequential scan is the right choice.'),
('PG-IDX-005', 'en', 'CAUSES', E'- No index on the WHERE or JOIN columns of a frequent query\n- An index exists but does not fit the query: column order, a function or a type cast (lower(email), ::text, say) makes it unusable\n- Stale statistics lead the planner to a full scan\n- Reporting or batch jobs that read most of the table (then this is fine)'),
('PG-IDX-005', 'en', 'IMPACT', E'Now: every scan reads the whole table from disk or memory; a query that would take milliseconds with an index takes seconds, and disk I/O and CPU are shared with the whole system.\nIf it goes on: the time grows with the table; a query acceptable today slows down as the table grows and pushes other data out of the cache.'),
('PG-IDX-005', 'en', 'RECOMMENDATION', E'- Find the queries scanning the table: search pg_stat_statements for the table name, or log slow queries with log_min_duration_statement\n- Look at the query''s plan (EXPLAIN (ANALYZE, BUFFERS)); if the filter returns few rows, create a fitting index: CREATE INDEX CONCURRENTLY ... (no table lock)\n- If an index exists, see why it is not used: an expression, a type cast, stale statistics (ANALYZE)\n- If the query really reads most of the table (a report), this finding can be accepted\n- Cost: an index takes disk space and slows writes slightly; CONCURRENTLY needs no downtime.'),
('PG-IDX-005', 'en', 'FINDING', 'Table {table} in database {database_name} ({size_bytes}) was scanned from start to end {seq_scans} times, {share}% of its scans; each scan read on average {rows_per_scan} rows (the table has {live_rows}).'),
-- PG-LOCK-001 -----------------------------------------------------------------
('PG-LOCK-001', 'tr', 'NAME', 'Kilit beklemesi'),
('PG-LOCK-001', 'tr', 'HEALTHY', 'Toplama anında {warning} veya daha uzun süredir kilit bekleyen oturum yoktu.'),
('PG-LOCK-001', 'tr', 'MEANING', 'Bir oturum, başka bir oturumun tuttuğu kilidin bırakılmasını bekliyor. Bu kontrol toplama anını görür: o an bekleyen yoksa sağlıklı der; ne sıklıkla kilitlenme olduğunu görmek için Keystone''un sık toplaması gerekir.'),
('PG-LOCK-001', 'tr', 'CAUSES', E'- Bloklayan oturum transaction''ını açık bırakmış (idle in transaction): uygulama commit ya da rollback yapmayı unutmuş\n- Uzun süren bir güncelleme ya da toplu iş aynı satırları tutuyor\n- Tabloyu kilitleyen bir işlem (ALTER TABLE, VACUUM FULL, CREATE INDEX CONCURRENTLY olmadan) çalışıyor\n- Uygulamada aynı satırları farklı sırada güncelleyen işlemler'),
('PG-LOCK-001', 'tr', 'IMPACT', E'Şimdi: bekleyen oturumun işlemi ilerlemiyor; kullanıcı için "uygulama dondu" demektir. Arkasından gelen oturumlar da sıraya girer.\nBöyle devam ederse: bekleme zinciri büyür, bağlantılar dolmaya başlar; max_connections''a ulaşılırsa yeni bağlantı açılamaz ve uygulama tamamen durur.'),
('PG-LOCK-001', 'tr', 'RECOMMENDATION', E'- Bloklayan oturumun ne yaptığına bakın (kullanıcı, uygulama, durum ve son sorgu tabloda)\n- "idle in transaction" ise uygulamanın o noktada commit/rollback yapmadığı yeri bulun; acil durumda oturumu sonlandırın: SELECT pg_terminate_backend(<pid>); (yaptığı değişiklikler geri alınır)\n- Tekrarı önlemek için idle_in_transaction_session_timeout ve lock_timeout ayarlarını değerlendirin\n- Tablo kilitleyen bakım işlerini yoğun olmayan saatlere alın\n- Bedeli: pg_terminate_backend o oturumun yarım kalan işini geri alır; timeout ayarları reload ister ama uygulamanın hata yönetimini gerektirir.'),
('PG-LOCK-001', 'tr', 'FINDING', '{pid} numaralı oturum kilit bekliyor; bekleme süresi {waited_seconds}, onu bloklayan oturum: {blockers}.'),
('PG-LOCK-001', 'tr', 'FINDING_ALT', '{pid} numaralı oturum kilit bekliyor; bekleme süresi yaklaşık {waited_seconds} (PostgreSQL 14 öncesinde beklemenin başlangıcı bilinmez, sorgunun başlangıcından hesaplandı), onu bloklayan oturum: {blockers}.'),
('PG-LOCK-001', 'en', 'NAME', 'Lock waits'),
('PG-LOCK-001', 'en', 'HEALTHY', 'At collection time no session had been waiting on a lock for {warning} or longer.'),
('PG-LOCK-001', 'en', 'MEANING', 'A session waits for another session to release a lock. This check sees the moment of collection: if nothing waits then, it says healthy; how often locks happen needs Keystone to collect often.'),
('PG-LOCK-001', 'en', 'CAUSES', E'- The blocking session left its transaction open (idle in transaction): the application forgot to commit or roll back\n- A long update or batch job holds the same rows\n- An operation that locks the table (ALTER TABLE, VACUUM FULL, CREATE INDEX without CONCURRENTLY) is running\n- Application transactions that update the same rows in different orders'),
('PG-LOCK-001', 'en', 'IMPACT', E'Now: the waiting session''s work does not move; for the user, "the application froze". Sessions behind it queue up too.\nIf it goes on: the chain grows and connections fill up; at max_connections no new connection opens and the application stops entirely.'),
('PG-LOCK-001', 'en', 'RECOMMENDATION', E'- See what the blocking session is doing (user, application, state and last query are in the table)\n- If it is "idle in transaction", find where the application does not commit or roll back; in an emergency end the session: SELECT pg_terminate_backend(<pid>); (its changes are rolled back)\n- To prevent it, consider idle_in_transaction_session_timeout and lock_timeout\n- Move table-locking maintenance to quiet hours\n- Cost: pg_terminate_backend rolls back that session''s unfinished work; the timeouts need a reload but also error handling in the application.'),
('PG-LOCK-001', 'en', 'FINDING', 'Session {pid} is waiting on a lock, for {waited_seconds}; blocked by session {blockers}.'),
('PG-LOCK-001', 'en', 'FINDING_ALT', 'Session {pid} is waiting on a lock, for about {waited_seconds} (before PostgreSQL 14 the start of the wait is unknown; counted from the statement''s start); blocked by session {blockers}.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
