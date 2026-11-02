/*
===============================================================================
Migration No : 047
Version      : V047
Title        : Configuration Dictionary

Author       : Hasan Tatarlı
Applies To   : Keystone Core

Description
-----------
ADR-0017 step 2: the settings Keystone recommends and the numbers behind the
recommendations. Logic stays in code (one calculation per setting, step 3);
factors, acceptable ranges and limits are data, changed by migrations.
===============================================================================
*/


/*
Design notes (2026-11-02, Hasan)
- Only general best practice: the PostgreSQL documentation or widely accepted
  practice (PGTune). Settings tuned by experience are left out.
- 18 settings, PostgreSQL 15-18. effective_io_concurrency only on 15-17: 18
  changed it (asynchronous I/O) and there is no recommendation for it yet.
- Acceptable range: range_low / range_high are multiples of the recommended
  value; accept_min / accept_max are plain values; accept_values lists the
  accepted words of an ENUM or BOOLEAN setting. Which key is present decides.
- A parameter row may be limited to a workload type, a storage type and a
  first version; the most specific matching row wins (code). setting_key NULL
  means a general number used by several settings.
- Units: BYTE, SECOND, RATIO, COUNT, NUMBER, TEXT. Settings are compared in
  these units; the calculation converts pg_settings units (kB, 8kB, ms...).
*/


/* ============================================================================
   TABLES
   ============================================================================ */

CREATE TABLE keystone.config_setting
(
    provider       VARCHAR(50)  NOT NULL,
    setting_key    VARCHAR(64)  NOT NULL,
    group_key      VARCHAR(20)  NOT NULL,
    value_type     VARCHAR(10)  NOT NULL,
    min_version    INTEGER,                      -- first major version; NULL: every supported version
    max_version    INTEGER,                      -- last major version; NULL: still present
    display_order  INTEGER      NOT NULL,

    CONSTRAINT pk_config_setting PRIMARY KEY (provider, setting_key),
    CONSTRAINT ck_config_setting_group
        CHECK (group_key IN ('MEMORY', 'WAL', 'STORAGE', 'PARALLEL', 'OBSERVABILITY')),
    CONSTRAINT ck_config_setting_value_type
        CHECK (value_type IN ('BYTE', 'SECOND', 'COUNT', 'NUMBER', 'ENUM', 'BOOLEAN')),
    CONSTRAINT ck_config_setting_versions
        CHECK (min_version IS NULL OR max_version IS NULL OR min_version <= max_version)
);

COMMENT ON TABLE keystone.config_setting IS
'Settings Keystone recommends (ADR-0017): group, value type and the major versions that have them.';


CREATE TABLE keystone.config_setting_text
(
    provider       VARCHAR(50)  NOT NULL,
    setting_key    VARCHAR(64)  NOT NULL,
    language_code  VARCHAR(10)  NOT NULL,
    text_type      VARCHAR(20)  NOT NULL,
    text           TEXT         NOT NULL,

    CONSTRAINT pk_config_setting_text PRIMARY KEY (provider, setting_key, language_code, text_type),
    CONSTRAINT fk_config_setting_text_setting
        FOREIGN KEY (provider, setting_key) REFERENCES keystone.config_setting (provider, setting_key),
    CONSTRAINT fk_config_setting_text_language
        FOREIGN KEY (language_code) REFERENCES keystone.dictionary_language (language_code),
    CONSTRAINT ck_config_setting_text_type CHECK (text_type IN ('REASON'))
);

COMMENT ON TABLE keystone.config_setting_text IS
'Why a setting matters, per language; the calculation itself is written by the code.';


CREATE TABLE keystone.config_parameter
(
    config_parameter_id  BIGINT GENERATED ALWAYS AS IDENTITY,
    provider             VARCHAR(50)    NOT NULL,
    setting_key          VARCHAR(64),             -- NULL: general number
    parameter_key        VARCHAR(64)    NOT NULL,
    workload_type        VARCHAR(10),             -- NULL: every workload
    storage_type         VARCHAR(10),             -- NULL: every storage type
    min_version          INTEGER,                 -- NULL: every version
    value_numeric        NUMERIC(24,6),
    value_text           TEXT,
    unit                 VARCHAR(10)    NOT NULL,
    description          TEXT,

    CONSTRAINT pk_config_parameter PRIMARY KEY (config_parameter_id),
    CONSTRAINT fk_config_parameter_setting
        FOREIGN KEY (provider, setting_key) REFERENCES keystone.config_setting (provider, setting_key),
    CONSTRAINT ck_config_parameter_workload CHECK (workload_type IN ('OLTP', 'OLAP', 'MIXED')),
    CONSTRAINT ck_config_parameter_storage  CHECK (storage_type IN ('SSD', 'HDD')),
    CONSTRAINT ck_config_parameter_unit
        CHECK (unit IN ('BYTE', 'SECOND', 'RATIO', 'COUNT', 'NUMBER', 'TEXT')),
    CONSTRAINT ck_config_parameter_value
        CHECK ((value_numeric IS NULL) <> (value_text IS NULL)
               AND ((unit = 'TEXT') = (value_text IS NOT NULL)))
);

CREATE UNIQUE INDEX uq_config_parameter_scope ON keystone.config_parameter
    (provider, COALESCE(setting_key, ''), parameter_key, COALESCE(workload_type, ''),
     COALESCE(storage_type, ''), COALESCE(min_version, 0));

COMMENT ON TABLE keystone.config_parameter IS
'Numbers of the configuration recommendations (ADR-0017); the most specific row by workload, storage and version wins.';


/* ============================================================================
   SETTINGS
   ============================================================================ */

INSERT INTO keystone.config_setting
    (provider, setting_key, group_key, value_type, min_version, max_version, display_order)
VALUES
('PostgreSQL', 'shared_buffers',                   'MEMORY',        'BYTE',    NULL, NULL,  10),
('PostgreSQL', 'effective_cache_size',             'MEMORY',        'BYTE',    NULL, NULL,  20),
('PostgreSQL', 'work_mem',                         'MEMORY',        'BYTE',    NULL, NULL,  30),
('PostgreSQL', 'maintenance_work_mem',             'MEMORY',        'BYTE',    NULL, NULL,  40),
('PostgreSQL', 'huge_pages',                       'MEMORY',        'ENUM',    NULL, NULL,  50),
('PostgreSQL', 'max_wal_size',                     'WAL',           'BYTE',    NULL, NULL, 110),
('PostgreSQL', 'min_wal_size',                     'WAL',           'BYTE',    NULL, NULL, 120),
('PostgreSQL', 'checkpoint_completion_target',     'WAL',           'NUMBER',  NULL, NULL, 130),
('PostgreSQL', 'checkpoint_timeout',               'WAL',           'SECOND',  NULL, NULL, 140),
('PostgreSQL', 'wal_buffers',                      'WAL',           'BYTE',    NULL, NULL, 150),
('PostgreSQL', 'random_page_cost',                 'STORAGE',       'NUMBER',  NULL, NULL, 210),
('PostgreSQL', 'effective_io_concurrency',         'STORAGE',       'COUNT',   NULL,   17, 220),
('PostgreSQL', 'max_worker_processes',             'PARALLEL',      'COUNT',   NULL, NULL, 310),
('PostgreSQL', 'max_parallel_workers',             'PARALLEL',      'COUNT',   NULL, NULL, 320),
('PostgreSQL', 'max_parallel_workers_per_gather',  'PARALLEL',      'COUNT',   NULL, NULL, 330),
('PostgreSQL', 'max_parallel_maintenance_workers', 'PARALLEL',      'COUNT',   NULL, NULL, 340),
('PostgreSQL', 'log_min_duration_statement',       'OBSERVABILITY', 'SECOND',  NULL, NULL, 410),
('PostgreSQL', 'track_io_timing',                  'OBSERVABILITY', 'BOOLEAN', NULL, NULL, 420);


/* ============================================================================
   NUMBERS
   ============================================================================ */

INSERT INTO keystone.config_parameter
    (provider, setting_key, parameter_key, workload_type, storage_type, value_numeric, value_text, unit, description)
VALUES
-- General -------------------------------------------------------------------
('PostgreSQL', NULL, 'non_dedicated_memory_share', NULL, NULL, 0.5, NULL, 'RATIO',
 'Share of memory PostgreSQL may use when the server also runs other software.'),
('PostgreSQL', NULL, 'parallel_min_cpus', NULL, NULL, 4, NULL, 'COUNT',
 'Below this many CPUs parallelism settings are not recommended (PGTune).'),

-- Memory --------------------------------------------------------------------
('PostgreSQL', 'shared_buffers', 'memory_share', NULL, NULL, 0.25, NULL, 'RATIO', '25 % of memory (documentation).'),
('PostgreSQL', 'shared_buffers', 'min', NULL, NULL, 134217728, NULL, 'BYTE', '128 MB, the default.'),
('PostgreSQL', 'shared_buffers', 'range_low', NULL, NULL, 0.6, NULL, 'RATIO', '15 % of memory.'),
('PostgreSQL', 'shared_buffers', 'range_high', NULL, NULL, 1.6, NULL, 'RATIO', '40 % of memory.'),

('PostgreSQL', 'effective_cache_size', 'memory_share', NULL, NULL, 0.75, NULL, 'RATIO', '75 % of memory.'),
('PostgreSQL', 'effective_cache_size', 'range_low', NULL, NULL, 0.67, NULL, 'RATIO', '50 % of memory.'),
('PostgreSQL', 'effective_cache_size', 'range_high', NULL, NULL, 1.2, NULL, 'RATIO', '90 % of memory.'),

('PostgreSQL', 'work_mem', 'connection_factor', 'OLTP',  NULL, 4, NULL, 'NUMBER', 'Sort/hash operations per connection assumed.'),
('PostgreSQL', 'work_mem', 'connection_factor', 'MIXED', NULL, 2, NULL, 'NUMBER', NULL),
('PostgreSQL', 'work_mem', 'connection_factor', 'OLAP',  NULL, 1, NULL, 'NUMBER', NULL),
('PostgreSQL', 'work_mem', 'min', NULL, NULL, 4194304, NULL, 'BYTE', '4 MB, the default.'),
('PostgreSQL', 'work_mem', 'max', 'OLTP',  NULL, 67108864, NULL, 'BYTE', '64 MB.'),
('PostgreSQL', 'work_mem', 'max', 'MIXED', NULL, 268435456, NULL, 'BYTE', '256 MB.'),
('PostgreSQL', 'work_mem', 'max', 'OLAP',  NULL, 1073741824, NULL, 'BYTE', '1 GB.'),
('PostgreSQL', 'work_mem', 'range_low', NULL, NULL, 0.25, NULL, 'RATIO', 'Wide: often tuned per session.'),
('PostgreSQL', 'work_mem', 'range_high', NULL, NULL, 4, NULL, 'RATIO', NULL),

('PostgreSQL', 'maintenance_work_mem', 'memory_share', NULL, NULL, 0.0625, NULL, 'RATIO', 'Memory / 16 (PGTune).'),
('PostgreSQL', 'maintenance_work_mem', 'min', NULL, NULL, 67108864, NULL, 'BYTE', '64 MB, the default.'),
('PostgreSQL', 'maintenance_work_mem', 'max', NULL, NULL, 2147483648, NULL, 'BYTE', '2 GB; more rarely helps.'),
('PostgreSQL', 'maintenance_work_mem', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'maintenance_work_mem', 'range_high', NULL, NULL, 2, NULL, 'RATIO', NULL),

('PostgreSQL', 'huge_pages', 'value', NULL, NULL, NULL, 'try', 'TEXT', 'The default.'),
('PostgreSQL', 'huge_pages', 'accept_values', NULL, NULL, NULL, 'try,on', 'TEXT', NULL),

-- WAL / checkpoint ----------------------------------------------------------
('PostgreSQL', 'max_wal_size', 'value', 'OLTP',  NULL, 4294967296, NULL, 'BYTE', '4 GB (PGTune).'),
('PostgreSQL', 'max_wal_size', 'value', 'MIXED', NULL, 8589934592, NULL, 'BYTE', '8 GB.'),
('PostgreSQL', 'max_wal_size', 'value', 'OLAP',  NULL, 17179869184, NULL, 'BYTE', '16 GB.'),
('PostgreSQL', 'max_wal_size', 'max_disk_share', NULL, NULL, 0.10, NULL, 'RATIO', 'Never more than 10 % of the data disk.'),
('PostgreSQL', 'max_wal_size', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'max_wal_size', 'range_high', NULL, NULL, 4, NULL, 'RATIO', NULL),

('PostgreSQL', 'min_wal_size', 'max_wal_size_share', NULL, NULL, 0.25, NULL, 'RATIO', 'max_wal_size / 4 (PGTune).'),
('PostgreSQL', 'min_wal_size', 'range_low', NULL, NULL, 0.25, NULL, 'RATIO', NULL),
('PostgreSQL', 'min_wal_size', 'range_high', NULL, NULL, 4, NULL, 'RATIO', NULL),

('PostgreSQL', 'checkpoint_completion_target', 'value', NULL, NULL, 0.9, NULL, 'NUMBER', 'Default since PostgreSQL 14.'),
('PostgreSQL', 'checkpoint_completion_target', 'accept_min', NULL, NULL, 0.8, NULL, 'NUMBER', NULL),
('PostgreSQL', 'checkpoint_completion_target', 'accept_max', NULL, NULL, 0.95, NULL, 'NUMBER', NULL),

('PostgreSQL', 'checkpoint_timeout', 'value', NULL, NULL, 900, NULL, 'SECOND', '15 minutes.'),
('PostgreSQL', 'checkpoint_timeout', 'accept_min', NULL, NULL, 600, NULL, 'SECOND', NULL),
('PostgreSQL', 'checkpoint_timeout', 'accept_max', NULL, NULL, 1800, NULL, 'SECOND', NULL),

('PostgreSQL', 'wal_buffers', 'value', NULL, NULL, 16777216, NULL, 'BYTE', '16 MB, the automatic value from 512 MB shared_buffers.'),
('PostgreSQL', 'wal_buffers', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'wal_buffers', 'range_high', NULL, NULL, 4, NULL, 'RATIO', NULL),

-- Storage -------------------------------------------------------------------
('PostgreSQL', 'random_page_cost', 'value', NULL, 'SSD', 1.1, NULL, 'NUMBER', NULL),
('PostgreSQL', 'random_page_cost', 'value', NULL, 'HDD', 4.0, NULL, 'NUMBER', 'The default.'),
('PostgreSQL', 'random_page_cost', 'accept_min', NULL, 'SSD', 1.0, NULL, 'NUMBER', NULL),
('PostgreSQL', 'random_page_cost', 'accept_max', NULL, 'SSD', 2.0, NULL, 'NUMBER', NULL),
('PostgreSQL', 'random_page_cost', 'accept_min', NULL, 'HDD', 2.0, NULL, 'NUMBER', NULL),
('PostgreSQL', 'random_page_cost', 'accept_max', NULL, 'HDD', 4.0, NULL, 'NUMBER', NULL),

('PostgreSQL', 'effective_io_concurrency', 'value', NULL, 'SSD', 200, NULL, 'COUNT', NULL),
('PostgreSQL', 'effective_io_concurrency', 'value', NULL, 'HDD', 2, NULL, 'COUNT', NULL),
('PostgreSQL', 'effective_io_concurrency', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'effective_io_concurrency', 'range_high', NULL, NULL, 2, NULL, 'RATIO', NULL),

-- Parallelism (only with parallel_min_cpus or more) -------------------------
('PostgreSQL', 'max_worker_processes', 'min', NULL, NULL, 8, NULL, 'COUNT', 'The default.'),
('PostgreSQL', 'max_worker_processes', 'cpu_share', NULL, NULL, 1, NULL, 'RATIO', 'One per CPU (PGTune).'),
('PostgreSQL', 'max_worker_processes', 'range_low', NULL, NULL, 1, NULL, 'RATIO',
 'Lower bound only: extensions and replication use these workers too.'),

('PostgreSQL', 'max_parallel_workers', 'cpu_share', NULL, NULL, 1, NULL, 'RATIO', 'One per CPU (PGTune).'),
('PostgreSQL', 'max_parallel_workers', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'max_parallel_workers', 'range_high', NULL, NULL, 2, NULL, 'RATIO', NULL),

('PostgreSQL', 'max_parallel_workers_per_gather', 'cpu_share', NULL, NULL, 0.5, NULL, 'RATIO', 'Half the CPUs, rounded up (PGTune).'),
('PostgreSQL', 'max_parallel_workers_per_gather', 'max', NULL, NULL, 4, NULL, 'COUNT', NULL),
('PostgreSQL', 'max_parallel_workers_per_gather', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'max_parallel_workers_per_gather', 'range_high', NULL, NULL, 2, NULL, 'RATIO', NULL),

('PostgreSQL', 'max_parallel_maintenance_workers', 'cpu_share', NULL, NULL, 0.5, NULL, 'RATIO', 'Half the CPUs, rounded up (PGTune).'),
('PostgreSQL', 'max_parallel_maintenance_workers', 'max', NULL, NULL, 4, NULL, 'COUNT', NULL),
('PostgreSQL', 'max_parallel_maintenance_workers', 'range_low', NULL, NULL, 0.5, NULL, 'RATIO', NULL),
('PostgreSQL', 'max_parallel_maintenance_workers', 'range_high', NULL, NULL, 2, NULL, 'RATIO', NULL),

-- Observability -------------------------------------------------------------
('PostgreSQL', 'log_min_duration_statement', 'value', NULL, NULL, 1, NULL, 'SECOND', NULL),
('PostgreSQL', 'log_min_duration_statement', 'accept_min', NULL, NULL, 0.25, NULL, 'SECOND', NULL),
('PostgreSQL', 'log_min_duration_statement', 'accept_max', NULL, NULL, 10, NULL, 'SECOND', NULL),

('PostgreSQL', 'track_io_timing', 'value', NULL, NULL, NULL, 'on', 'TEXT', NULL),
('PostgreSQL', 'track_io_timing', 'accept_values', NULL, NULL, NULL, 'on', 'TEXT', NULL);


/* ============================================================================
   TEXTS
   ============================================================================ */

INSERT INTO keystone.config_setting_text (provider, setting_key, language_code, text_type, text) VALUES
('PostgreSQL', 'shared_buffers', 'tr', 'REASON',
 'PostgreSQL''in kendi veri önbelleği. Belleğin yaklaşık dörtte biri önerilir; kalanı işletim sisteminin dosya önbelleğine ve sorgulara kalır.'),
('PostgreSQL', 'shared_buffers', 'en', 'REASON',
 'PostgreSQL''s own data cache. About a quarter of memory is recommended; the rest stays for the operating system''s file cache and queries.'),
('PostgreSQL', 'effective_cache_size', 'tr', 'REASON',
 'Bellek ayırmaz; planner''a veri için ne kadar önbellek olduğunu söyler. Düşükse planner index kullanmaktan kaçınabilir.'),
('PostgreSQL', 'effective_cache_size', 'en', 'REASON',
 'Allocates nothing; tells the planner how much cache the data has. Too low, and the planner may avoid indexes.'),
('PostgreSQL', 'work_mem', 'tr', 'REASON',
 'Her sort ve hash işleminin diske taşmadan kullanabileceği bellek. Bir sorgu birden fazla işlem yapabildiği için bağlantı sayısıyla birlikte düşünülür.'),
('PostgreSQL', 'work_mem', 'en', 'REASON',
 'Memory each sort or hash operation may use before spilling to disk. A query can run several of them, so it is weighed against the number of connections.'),
('PostgreSQL', 'maintenance_work_mem', 'tr', 'REASON',
 'VACUUM, CREATE INDEX ve benzeri bakım işlemlerinin belleği. Yeterli olduğunda bakım işlemleri belirgin şekilde hızlanır.'),
('PostgreSQL', 'maintenance_work_mem', 'en', 'REASON',
 'Memory for VACUUM, CREATE INDEX and other maintenance. Enough of it makes maintenance markedly faster.'),
('PostgreSQL', 'huge_pages', 'tr', 'REASON',
 'Büyük bellek sayfaları paylaşılan belleğin yönetim yükünü azaltır. try, işletim sistemi destekliyorsa kullanır, desteklemiyorsa normal sayfalarla devam eder.'),
('PostgreSQL', 'huge_pages', 'en', 'REASON',
 'Huge pages reduce the cost of managing shared memory. try uses them when the operating system offers them and starts without them otherwise.'),
('PostgreSQL', 'max_wal_size', 'tr', 'REASON',
 'Checkpoint''ler arasında birikebilecek WAL miktarı. Küçükse checkpoint''ler sıklaşır ve yazma yükü artar.'),
('PostgreSQL', 'max_wal_size', 'en', 'REASON',
 'How much WAL may build up between checkpoints. Too small, and checkpoints come more often and add write load.'),
('PostgreSQL', 'min_wal_size', 'tr', 'REASON',
 'Silinmeyip yeniden kullanılan WAL miktarı; yoğun yazma anlarında yeni dosya oluşturma maliyetini azaltır.'),
('PostgreSQL', 'min_wal_size', 'en', 'REASON',
 'WAL kept for reuse instead of removed; saves creating new files during bursts of writes.'),
('PostgreSQL', 'checkpoint_completion_target', 'tr', 'REASON',
 'Checkpoint yazmasını checkpoint aralığına yayar; ani disk yüklerini önler.'),
('PostgreSQL', 'checkpoint_completion_target', 'en', 'REASON',
 'Spreads checkpoint writes over the checkpoint interval and avoids sudden disk load.'),
('PostgreSQL', 'checkpoint_timeout', 'tr', 'REASON',
 'Zamanlanmış checkpoint aralığı. Çok kısa olursa gereksiz yazma yükü oluşur, çok uzun olursa çökme sonrası açılış süresi uzar.'),
('PostgreSQL', 'checkpoint_timeout', 'en', 'REASON',
 'Interval of timed checkpoints. Too short adds needless writes; too long makes recovery after a crash slower.'),
('PostgreSQL', 'wal_buffers', 'tr', 'REASON',
 'Diske yazılmadan önce WAL''in tutulduğu bellek. Yoğun yazmada küçük olması commit''leri yavaşlatır.'),
('PostgreSQL', 'wal_buffers', 'en', 'REASON',
 'Memory holding WAL before it is written. Too small slows commits under heavy writes.'),
('PostgreSQL', 'random_page_cost', 'tr', 'REASON',
 'Planner''ın rastgele disk okumasına biçtiği maliyet. SSD''de rastgele okuma ucuzdur; HDD değeri bırakılırsa planner index''lerden kaçınır.'),
('PostgreSQL', 'random_page_cost', 'en', 'REASON',
 'The planner''s cost of a random disk read. Random reads are cheap on SSD; left at the HDD value, the planner avoids indexes.'),
('PostgreSQL', 'effective_io_concurrency', 'tr', 'REASON',
 'Diskten aynı anda kaç okuma istenebileceği. SSD çok sayıda eşzamanlı isteği kaldırır.'),
('PostgreSQL', 'effective_io_concurrency', 'en', 'REASON',
 'How many reads may be requested from disk at once. SSDs handle many concurrent requests.'),
('PostgreSQL', 'max_worker_processes', 'tr', 'REASON',
 'Arka plan worker''larının toplam sınırı; paralel sorgular, replication ve extension''lar bu havuzu kullanır. Restart gerektirir.'),
('PostgreSQL', 'max_worker_processes', 'en', 'REASON',
 'Total limit of background workers; parallel queries, replication and extensions share it. Needs a restart.'),
('PostgreSQL', 'max_parallel_workers', 'tr', 'REASON',
 'Aynı anda çalışabilecek paralel sorgu worker''larının toplamı.'),
('PostgreSQL', 'max_parallel_workers', 'en', 'REASON',
 'Total parallel query workers running at once.'),
('PostgreSQL', 'max_parallel_workers_per_gather', 'tr', 'REASON',
 'Tek bir sorgunun kullanabileceği paralel worker sayısı; bir sorgunun bütün CPU''ları kaplamasını önler.'),
('PostgreSQL', 'max_parallel_workers_per_gather', 'en', 'REASON',
 'Parallel workers one query may use; keeps a single query from taking every CPU.'),
('PostgreSQL', 'max_parallel_maintenance_workers', 'tr', 'REASON',
 'CREATE INDEX ve VACUUM''un kullanabileceği paralel worker sayısı.'),
('PostgreSQL', 'max_parallel_maintenance_workers', 'en', 'REASON',
 'Parallel workers CREATE INDEX and VACUUM may use.'),
('PostgreSQL', 'log_min_duration_statement', 'tr', 'REASON',
 'Bu süreden uzun süren sorgular loglanır. Kapalıysa yavaş sorgular görünmez; 0 ise her sorgu loglanır ve disk ile performans zorlanır.'),
('PostgreSQL', 'log_min_duration_statement', 'en', 'REASON',
 'Queries running longer than this are logged. Off, slow queries stay invisible; at 0 every query is logged, which strains disk and performance.'),
('PostgreSQL', 'track_io_timing', 'tr', 'REASON',
 'Disk okuma ve yazma sürelerini ölçer; yavaşlığın diskten mi geldiği ancak böyle anlaşılır. Açmadan önce pg_test_timing ile zamanlama maliyeti ölçülmelidir.'),
('PostgreSQL', 'track_io_timing', 'en', 'REASON',
 'Measures disk read and write time; only then can slowness be traced to the disk. Measure timing overhead with pg_test_timing before turning it on.');
