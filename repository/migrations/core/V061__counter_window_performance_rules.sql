/*
===============================================================================
Migration No : 061
Version      : V061

Title        : Counter Window and Performance Rules
Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
Adds the PG_PERFORMANCE_HEALTH assessment with topic PERFORMANCE and the
rules PG-PERF-003 Checkpoint Pressure and PG-PERF-002 Low Cache Hit Ratio,
and PG-CAP-005 Heavy Temporary File Use in PG_CAPACITY_HEALTH. They read
cumulative counters (PG_CHECKPOINT_STATS, PG_DATABASE_STATS from provider
migration PG024) over a window per rule.
===============================================================================
*/


/*
Design notes (2026-11-13, Hasan)
--------------------------------
- Counters are cumulative. A rule compares the newest snapshot with the
  oldest one inside its window (same stats_reset, no counter lower: a reset or
  a failover breaks the series). Without one, the counters since stats_reset
  when that is known; ratios (checkpoints, cache hit) may also use the
  counters since an unknown start, rates (temporary bytes per day) may not.
  Statistics younger than min_window are not judged.
- Window and min_window are per rule: the window follows how fast the
  metric changes; six hours of statistics already tell something.
- PG-PERF-003 warns from 20 % requested (Hasan): the same line as the
  max_wal_size recommendation (PG-CONF-003, requested_share_limit 0.2), so a
  report never recommends a larger max_wal_size while calling this healthy.
- PG-CAP-005 measured over less than a day: the finding says it and is at
  most WARNING, as a nightly batch can fall in or out of a short period.
- PG-PERF-002 judges active databases only (min_blocks read in the period);
  its observed value is the share read from disk (100 - hit ratio), so the
  thresholds stay "value >= threshold".
- Crisis alerting stays with monitoring (ADR-0005, ADR-0013): a disk filling
  up is PG-CAP-001's finding; PG-CAP-005 shows the habit behind it.
- Texts: IMPACT says what happens now and if it goes on; RECOMMENDATION ends
  with what the fix costs.
===============================================================================
*/


/* ============================================================================
   TOPIC AND ASSESSMENT
   ============================================================================ */

INSERT INTO keystone.dictionary_topic (topic_key, display_order) VALUES
    ('PERFORMANCE', 65)
ON CONFLICT (topic_key) DO NOTHING;

INSERT INTO keystone.dictionary_topic_text (topic_key, language_code, name) VALUES
    ('PERFORMANCE', 'tr', 'Performans'),
    ('PERFORMANCE', 'en', 'Performance')
ON CONFLICT (topic_key, language_code) DO NOTHING;

INSERT INTO keystone.assessment_definition
    (assessment_key, name, provider, description, default_interval_seconds)
VALUES
    ('PG_PERFORMANCE_HEALTH', 'Performance Health', 'PostgreSQL',
     'Evaluates cumulative activity counters over a window: checkpoints and cache use.',
     3600)
ON CONFLICT (assessment_key) DO NOTHING;


/* ============================================================================
   RULE DEFINITIONS
   ============================================================================ */

INSERT INTO keystone.rule_definition
    (assessment_id, rule_key, name, description, evidence_source, default_severity,
     finding_template, recommendation, topic_key)
SELECT ad.assessment_id, r.rule_key, r.name, r.description, r.evidence_source, NULL,
       r.finding_template, r.recommendation, r.topic_key
FROM (VALUES
    ('PG_PERFORMANCE_HEALTH', 'PG-PERF-003', 'Checkpoint Pressure',
     'Detects requested checkpoints (WAL reaching max_wal_size) dominating timed ones over a window.',
     'PG_CHECKPOINT_STATS',
     '{share}% of {total} checkpoints were requested before their time because WAL filled up ({requested} checkpoints).',
     'Raise max_wal_size so that checkpoints are mostly timed.', 'PERFORMANCE'),
    ('PG_PERFORMANCE_HEALTH', 'PG-PERF-002', 'Low Cache Hit Ratio',
     'Detects active databases that read a large share of their blocks from disk instead of shared buffers.',
     'PG_DATABASE_STATS',
     'Database {database_name} found {hit}% of its blocks in memory; {read_blocks} blocks were read from disk.',
     'Find the queries that read most from disk before adding memory.', 'PERFORMANCE'),
    ('PG_CAPACITY_HEALTH', 'PG-CAP-005', 'Heavy Temporary File Use',
     'Detects databases whose queries write many temporary files: sorts and hashes that do not fit work_mem.',
     'PG_DATABASE_STATS',
     'Database {database_name} wrote {temp_bytes} to {temp_files} temporary files in {period_seconds} seconds (about {per_day} bytes per day).',
     'Find the queries that write temporary files; give them more work_mem or make them process fewer rows.',
     'STORAGE')
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
    ('PG-PERF-003', 'WARNING',  20,           'PERCENT'),
    ('PG-PERF-002', 'WARNING',  5,            'PERCENT'),
    ('PG-CAP-005',  'WARNING',  10737418240,  'BYTE_PER_DAY'),
    ('PG-CAP-005',  'CRITICAL', 107374182400, 'BYTE_PER_DAY')
) AS t (rule_key, severity, threshold_value, threshold_unit) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, severity) DO NOTHING;

INSERT INTO keystone.rule_parameter (rule_id, parameter_key, parameter_value, parameter_unit, description)
SELECT rd.rule_id, p.parameter_key, p.parameter_value, p.parameter_unit, p.description
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-PERF-003', 'window',          86400,   'SECOND', 'Counters are compared with the oldest snapshot within this window.'),
    ('PG-PERF-003', 'min_window',      21600,   'SECOND', 'Statistics younger than this are not judged.'),
    ('PG-PERF-003', 'min_checkpoints', 10,      'COUNT',  'Fewer checkpoints in the period are not judged.'),
    ('PG-PERF-002', 'window',          86400,   'SECOND', 'Counters are compared with the oldest snapshot within this window.'),
    ('PG-PERF-002', 'min_window',      21600,   'SECOND', 'Statistics younger than this are not judged.'),
    ('PG-PERF-002', 'min_blocks',      1000000, 'BLOCK',  'Databases that read fewer blocks in the period are not judged.'),
    ('PG-CAP-005',  'window',          86400,   'SECOND', 'Counters are compared with the oldest snapshot within this window.'),
    ('PG-CAP-005',  'min_window',      21600,   'SECOND', 'Statistics younger than this are not judged.')
) AS p (rule_key, parameter_key, parameter_value, parameter_unit, description) ON p.rule_key = rd.rule_key
ON CONFLICT (rule_id, parameter_key) DO NOTHING;

INSERT INTO keystone.rule_evidence_requirement (rule_id, evidence_source, is_required, max_age_seconds)
SELECT rd.rule_id, rd.evidence_source, TRUE, 3600
FROM keystone.rule_definition rd
WHERE rd.rule_key IN ('PG-PERF-003', 'PG-PERF-002', 'PG-CAP-005')
ON CONFLICT (rule_id, evidence_source) DO NOTHING;

INSERT INTO keystone.rule_impact_category (rule_id, category_key)
SELECT rd.rule_id, c.category_key
FROM keystone.rule_definition rd
JOIN (VALUES
    ('PG-PERF-003', 'PERFORMANCE'),
    ('PG-PERF-002', 'PERFORMANCE'),
    ('PG-CAP-005',  'PERFORMANCE'),
    ('PG-CAP-005',  'CAPACITY')
) AS c (rule_key, category_key) ON c.rule_key = rd.rule_key
ON CONFLICT (rule_id, category_key) DO NOTHING;


/* ============================================================================
   TEXTS
   ============================================================================ */

INSERT INTO keystone.rule_text (rule_id, language_code, text_type, text)
SELECT rd.rule_id, t.language_code, t.text_type, t.text
FROM keystone.rule_definition rd
JOIN (VALUES
-- PG-PERF-003 -----------------------------------------------------------------
('PG-PERF-003', 'tr', 'NAME', 'Zorunlu checkpoint baskısı'),
('PG-PERF-003', 'tr', 'HEALTHY', 'Checkpoint''lerin çoğu zamanında yapılıyor; WAL dolduğu için zorunlu checkpoint oranı {warning} altında.'),
('PG-PERF-003', 'tr', 'MEANING', 'Checkpoint''lerin önemli bir kısmı zamanı (checkpoint_timeout) gelmeden, WAL max_wal_size''a ulaştığı için zorla yapılıyor; max_wal_size yazma yüküne yetmiyor.'),
('PG-PERF-003', 'tr', 'CAUSES', E'- max_wal_size varsayılan ya da küçük bir değerde bırakılmış\n- Yazma yükü (toplu yükleme, büyük güncellemeler, gece işleri) zamanla artmış\n- Elle CHECKPOINT çalıştıran ya da sık yedek başlatan işler (bunlar da zorunlu sayılır)'),
('PG-PERF-003', 'tr', 'IMPACT', E'Şimdi: her zorunlu checkpoint birikmiş değişiklikleri kısa sürede diske yazar; yoğun yazma saatlerinde disk tıkanır ve sorgular dalgalı biçimde yavaşlar ("bazen yavaşlıyor, sonra düzeliyor"). Checkpoint''ten sonra her sayfanın ilk değişikliği WAL''a tam sayfa olarak yazıldığı için WAL hacmi de şişer.\nBöyle devam ederse: yazma yükü arttıkça oran kötüleşir; replica''lara giden trafik, WAL arşivi ve yedek alanı gereğinden büyür.'),
('PG-PERF-003', 'tr', 'RECOMMENDATION', E'- max_wal_size''ı artırın; konfigürasyon önerileri bölümündeki değer bu sistemin checkpoint sayılarından hesaplanır\n- ALTER SYSTEM SET max_wal_size = ''<değer>''; SELECT pg_reload_conf();\n- WAL''ın bulunduğu diskte bu kadar boş alan olduğunu doğrulayın\n- Bir gün sonra bu kontrolü tekrar çalıştırıp oranın düştüğünü görün\n- Bedeli: diskte max_wal_size kadar WAL tutulur ve çökmeden sonra açılış biraz uzar. İş: tek ayar ve reload, restart gerekmez.'),
('PG-PERF-003', 'tr', 'FINDING', '{total} checkpoint''in %{share} kadarı zamanı gelmeden, WAL dolduğu için yapıldı ({requested} checkpoint); ölçüm süresi tabloda.'),
('PG-PERF-003', 'en', 'NAME', 'Checkpoint pressure'),
('PG-PERF-003', 'en', 'HEALTHY', 'Most checkpoints are timed; the share requested because WAL filled up is below {warning}.'),
('PG-PERF-003', 'en', 'MEANING', 'A large share of checkpoints is requested before checkpoint_timeout because WAL reaches max_wal_size; max_wal_size is too small for the write load.'),
('PG-PERF-003', 'en', 'CAUSES', E'- max_wal_size was left at the default or a small value\n- The write load (bulk loads, large updates, nightly jobs) grew over time\n- Jobs that run CHECKPOINT by hand or start backups often (these count as requested too)'),
('PG-PERF-003', 'en', 'IMPACT', E'Now: every requested checkpoint writes the accumulated changes to disk in a short time; at busy write hours the disk saturates and queries slow down in waves ("sometimes slow, then fine"). After a checkpoint the first change of every page goes to WAL as a full page, so WAL volume grows too.\nIf it goes on: the share worsens as the write load grows; traffic to replicas, the WAL archive and backup space grow more than needed.'),
('PG-PERF-003', 'en', 'RECOMMENDATION', E'- Raise max_wal_size; the value in the configuration recommendations is computed from this system''s checkpoint counts\n- ALTER SYSTEM SET max_wal_size = ''<value>''; SELECT pg_reload_conf();\n- Make sure the disk holding WAL has that much free space\n- Run this check again a day later and see the share fall\n- Cost: up to max_wal_size of WAL kept on disk, and a somewhat longer start after a crash. Work: one setting and a reload, no restart.'),
('PG-PERF-003', 'en', 'FINDING', '{share}% of {total} checkpoints were requested before their time because WAL filled up ({requested} checkpoints); the period is in the table.'),
-- PG-PERF-002 -----------------------------------------------------------------
('PG-PERF-002', 'tr', 'NAME', 'Düşük cache hit oranı'),
('PG-PERF-002', 'tr', 'HEALTHY', 'Aktif veritabanlarında okunan blokların diskten okunan payı {warning} altında; veri büyük ölçüde bellekten okunuyor.'),
('PG-PERF-002', 'tr', 'MEANING', 'Bu veritabanında okunan blokların önemli bir kısmı shared buffers''ta bulunamayıp diskten (ya da işletim sisteminin önbelleğinden) okunuyor. Bir sinyaldir, kesin teşhis değildir: diskten okunmuş görünen blokların bir kısmı işletim sisteminin önbelleğinden gelir; analitik iş yüklerinde düşük oran normaldir.'),
('PG-PERF-002', 'tr', 'CAUSES', E'- Sorgular gereğinden fazla veri okuyor: eksik index, tam tablo taramaları (çoğu zaman asıl sebep)\n- Sık kullanılan veri kümesi shared_buffers''a ya da sunucu belleğine sığmıyor\n- Büyük raporlama ya da toplu işler önbelleği sürekli değiştiriyor'),
('PG-PERF-002', 'tr', 'IMPACT', E'Şimdi: bellekten okunabilecek veri diskten okunuyor; sorgular yavaşlar ve disk I/O''su başka işlerle paylaşıldığı için bütün sistem etkilenir.\nBöyle devam ederse: veri büyüdükçe sığmayan pay artar; yavaşlama veri büyüklüğüyle birlikte kademeli olarak kötüleşir.'),
('PG-PERF-002', 'tr', 'RECOMMENDATION', E'- Önce en çok disk okuyan sorguları bulun (pg_stat_statements: shared_blks_read); çoğu zaman bir index ya da sorgu düzeltmesi bellek eklemekten ucuzdur\n- Ağır sequential scan yapılan büyük tabloları kontrol edin\n- Okuma gerçekten çalışan veri kümesinden geliyorsa shared_buffers''ı (restart) ya da sunucu belleğini artırmayı değerlendirin\n- Bedeli: sorgu ya da index düzeltmesi geliştirme işi ister; shared_buffers değişikliği restart, bellek eklemek donanım maliyeti demektir.'),
('PG-PERF-002', 'tr', 'FINDING', '{database_name} veritabanı blokların %{hit} kadarını bellekte buldu; {read_blocks} blok diskten okundu.'),
('PG-PERF-002', 'en', 'NAME', 'Low cache hit ratio'),
('PG-PERF-002', 'en', 'HEALTHY', 'In active databases the share of blocks read from disk is below {warning}; data is read mostly from memory.'),
('PG-PERF-002', 'en', 'MEANING', 'A large share of the blocks this database reads is not in shared buffers and comes from disk (or the operating system cache). A signal, not a diagnosis: some blocks counted as read from disk come from the operating system cache, and analytical workloads normally have lower ratios.'),
('PG-PERF-002', 'en', 'CAUSES', E'- Queries read more data than needed: missing indexes, full table scans (often the real cause)\n- The frequently used data does not fit shared_buffers or the server memory\n- Large reporting or batch jobs keep replacing the cache'),
('PG-PERF-002', 'en', 'IMPACT', E'Now: data that could be read from memory is read from disk; queries slow down, and since disk I/O is shared, the whole system feels it.\nIf it goes on: as data grows, the share that does not fit grows; the slowdown worsens gradually with data size.'),
('PG-PERF-002', 'en', 'RECOMMENDATION', E'- First find the queries that read most from disk (pg_stat_statements: shared_blks_read); an index or a query fix is often cheaper than memory\n- Check large tables read by heavy sequential scans\n- If the reads really come from the working set, consider raising shared_buffers (restart) or the server memory\n- Cost: a query or index fix is development work; shared_buffers needs a restart; memory is hardware cost.'),
('PG-PERF-002', 'en', 'FINDING', 'Database {database_name} found {hit}% of its blocks in memory; {read_blocks} blocks were read from disk.'),
-- PG-CAP-005 ------------------------------------------------------------------
('PG-CAP-005', 'tr', 'NAME', 'Yoğun geçici dosya kullanımı'),
('PG-CAP-005', 'tr', 'HEALTHY', 'Hiçbir veritabanı günde {warning} üzerinde geçici dosya yazmıyor.'),
('PG-CAP-005', 'tr', 'MEANING', 'Bu veritabanındaki sorguların sıralama ve hash işlemleri work_mem''e sığmayıp diske geçici dosya yazıyor. work_mem tek bir işlemin bellek sınırıdır; shared buffers''la ilgisi yoktur.'),
('PG-CAP-005', 'tr', 'CAUSES', E'- Sorgular gereğinden fazla satır işliyor: eksik filtre ya da index, kötü join planı, güncel olmayan istatistik (az sayıda ama çok büyük dosya bunu düşündürür)\n- work_mem gerçek iş yüküne göre düşük: raporlama ve toplu işler (çok sayıda orta büyüklükte dosya bunu düşündürür)\n- Tek seferlik büyük işler: index oluşturma, büyük veri aktarımı'),
('PG-CAP-005', 'tr', 'IMPACT', E'Şimdi: bellekte saniyeler sürecek işlemler diskte dakikalar sürer; geçici dosyalar data diskine yazıldığı için diğer sorguların I/O''sunu da yavaşlatır.\nBöyle devam ederse: veri büyüdükçe geçici dosyalar büyür. Tek bir kontrolsüz sorgu yüzlerce GB yazıp data diskini doldurabilir; disk dolarsa veritabanı yazamaz hale gelir (bunu PG-CAP-001 anında gösterir).'),
('PG-CAP-005', 'tr', 'RECOMMENDATION', E'- Geçici dosya yazan sorguları bulun: log_temp_files = ''100MB'' ayarıyla log''a düşerler (reload yeter); pg_stat_statements varsa temp_blks_written\n- Sorgu çok satır işliyorsa sorguyu, index''i ya da istatistikleri düzeltin\n- Sorgu doğru ama büyükse work_mem''i yalnızca o iş için verin: ALTER ROLE <rapor_kullanıcısı> SET work_mem = ''256MB''; ya da oturumda SET work_mem\n- work_mem''i sunucu genelinde artırmayın: değer işlem başına geçerlidir ve bağlantı sayısıyla çarpılır; bellek aşırı taahhüdüne yol açabilir (PG-CONF-007)\n- Bedeli: log_temp_files ve rol bazlı work_mem yalnızca reload; sorgu düzeltmesi geliştirme işi ister.'),
('PG-CAP-005', 'tr', 'FINDING', '{database_name} veritabanı son {period_seconds} içinde {temp_files} geçici dosyaya toplam {temp_bytes} yazdı (günde yaklaşık {per_day}).'),
('PG-CAP-005', 'tr', 'FINDING_ALT', '{database_name} veritabanı son {period_seconds} içinde {temp_files} geçici dosyaya toplam {temp_bytes} yazdı; bu, günde yaklaşık {per_day} eder. Süre bir günden kısa olduğu için bu bir eğilimdir: gece çalışan bir iş süreye girip çıkabilir.'),
('PG-CAP-005', 'en', 'NAME', 'Heavy temporary file use'),
('PG-CAP-005', 'en', 'HEALTHY', 'No database writes more than {warning} of temporary files per day.'),
('PG-CAP-005', 'en', 'MEANING', 'Sorts and hashes of queries in this database do not fit work_mem and write temporary files to disk. work_mem is the memory limit of a single operation; it is not shared buffers.'),
('PG-CAP-005', 'en', 'CAUSES', E'- Queries process more rows than needed: a missing filter or index, a poor join plan, stale statistics (few but very large files suggest this)\n- work_mem is low for the real workload: reporting and batch jobs (many medium-sized files suggest this)\n- One-off large operations: index builds, large data transfers'),
('PG-CAP-005', 'en', 'IMPACT', E'Now: operations that would take seconds in memory take minutes on disk; temporary files are written to the data disk and slow down other queries'' I/O too.\nIf it goes on: temporary files grow with the data. A single runaway query can write hundreds of GB and fill the data disk; a full disk stops the database from writing (PG-CAP-001 shows that at once).'),
('PG-CAP-005', 'en', 'RECOMMENDATION', E'- Find the queries that write temporary files: log_temp_files = ''100MB'' logs them (a reload is enough); with pg_stat_statements, temp_blks_written\n- If a query processes too many rows, fix the query, the index or the statistics\n- If the query is right but large, give work_mem to that job only: ALTER ROLE <report_user> SET work_mem = ''256MB''; or SET work_mem in the session\n- Do not raise work_mem server-wide: it applies per operation and multiplies with connections; it can overcommit memory (PG-CONF-007)\n- Cost: log_temp_files and per-role work_mem need only a reload; a query fix is development work.'),
('PG-CAP-005', 'en', 'FINDING', 'Database {database_name} wrote {temp_bytes} to {temp_files} temporary files in the last {period_seconds} (about {per_day} per day).'),
('PG-CAP-005', 'en', 'FINDING_ALT', 'Database {database_name} wrote {temp_bytes} to {temp_files} temporary files in the last {period_seconds}, about {per_day} per day. The period is shorter than a day, so this is a trend: a nightly job can fall in or out of it.')
) AS t (rule_key, language_code, text_type, text) ON t.rule_key = rd.rule_key
ON CONFLICT (rule_id, language_code, text_type) DO NOTHING;
