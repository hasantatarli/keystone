"""Health check report as one self-contained HTML file (MVP Plan Phase 1, report).

Two parts from the same data:
  1. Executive summary (CTO/CEO): verdict, affected impact categories, status
     per topic, main problems with impact and next step, in plain words.
  2. Technical details (DBA/IT manager): system overview, every finding with
     its context (who / where), rule results by topic, gaps, collected data.

Frame texts are in TEXTS; rule, topic and category texts come from the
Dictionary per language (V029). The file has no external resources, so it
can be e-mailed, opened offline and printed.

    python -m repository.report.health_check_report --health-check 1 --lang tr
    python -m repository.report.health_check_report --target 1          # latest check
"""

import argparse
from datetime import datetime, timedelta, timezone
import html
import json
import math
from pathlib import Path
import re

from repository.common.logging_config import configure_logging, get_logger
from repository.intelligence.assessment_engine import (
    CLOCK_SKEW_TOLERANCE_SECONDS, REFERENCE_SOURCES, data_mount, usage_percent)
from repository.intelligence import config_recommendations as config_rec
from repository.worker import worker


logger = get_logger("report")

DEFAULT_OUTPUT_DIR = "reports"
FALLBACK_LANGUAGE = "en"
SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


# -----------------------------------------------------------------------------
# Report frame texts. Add a language by adding a dictionary with the same keys.
# -----------------------------------------------------------------------------

TEXTS = {
    "tr": {
        "title": "Veritabanı Sağlık Kontrolü Raporu",
        "target": "Sistem", "date": "Tarih", "check_no": "Kontrol no", "requested_by": "Talep eden",
        "evidence": "Kanıt", "evidence_offline": "offline toplandı (müşteri tarafında salt okunur script'lerle), içe aktarıldı {imported}",
        "part_exec": "Yönetici Özeti", "part_tech": "Teknik Detaylar",
        "verdict_critical": "Acil müdahale gerektiren sorunlar var.",
        "verdict_warning": "Dikkat gerektiren sorunlar var.",
        "verdict_healthy": "Değerlendirilen alanlarda sorun bulunmadı.",
        "verdict_none": "Hiçbir kontrol değerlendirilemedi; veri toplanamadı.",
        "verdict_unassessed": "{n} kontrol yapılamadı.",
        "unassessed_title": "Değerlendirilemeyen kontroller",
        "unassessed_lead": "Bu kontroller yapılamadı; sistemde sorun olup olmadığı bilinmiyor.",
        "unassessed_collect": "{targets}: {source} toplanamadı{status}",
        "unassessed_affects": "Etkilenen kontroller",
        "unassessed_action": "Yapılması gereken",
        "action_CONNECTION_FAILED": "Keystone'un bu sunuculara bağlanabildiğini kontrol edin: ağ erişimi, pg_hba.conf, kullanıcı ve şifre.",
        "action_NOT_COLLECTED": "Bu sunucular için gereken bağlantıyı tanımlayın (SSH verisi için HOST bağlantısı).",
        "action_NOT_COLLECTED_offline": "Eksik dosyayı toplayın: sunucu bilgisi için veritabanı sunucusunda host script'ini (host_snapshot.sh ya da host_snapshot_windows.ps1) çalıştırın; diğerleri için toplayıcıyı yeniden çalıştırın.",
        "action_other": "Hata ayrıntısı teknik bölümde (Toplanan Veriler); sorunu giderip health check'i tekrarlayın.",
        "coverage": "Tanımlı {defined} kontrolden {total} tanesi bu sisteme uygulanabilir; {evaluated} tanesi sonuç verdi.",
        "not_assessed_note": "{count} kontrol yeterli veri olmadığı için değerlendirilemedi.",
        "not_applicable_note": "{count} kontrol bu sisteme uygulanmaz.",
        "count_critical": "Kritik", "count_warning": "Uyarı",
        "count_healthy": "Sağlıklı", "count_not_assessed": "Değerlendirilemedi",
        "inventory_title": "Sistem envanteri",
        "inv_servers": "Sunucu", "inv_version": "PostgreSQL", "inv_cpu": "CPU", "inv_memory": "Bellek",
        "inv_data": "Veri", "inv_disk": "Disk",
        "inv_roles": "{primary} primary, {replica} replica", "inv_cores": "{n} çekirdek",
        "inv_unknown_replicas": "{n} bağlı replica değerlendirilmedi",
        "unknown_replica_cause": "Primary'ye bağlı {n} replica Keystone'da tanımlı değil ve bu kontrolde değerlendirilmedi: {list}.",
        "unknown_replica_action": "Bu sunucuları da toplayın (offline script'i onlarda da çalıştırın ya da bağlantılarını tanımlayın); ayarları, diski ve sürümü ancak o zaman değerlendirilir.",
        "inv_databases": "{n} veritabanı", "inv_partial": "{known} / {total} sunucu için",
        "inv_unknown": "Toplanamadı", "percent": "%{n}", "inv_full": "{p} dolu",
        "inv_data_disk": "Veri diski", "inv_role": "Rol", "inv_disk_unknown": "Bilinmiyor",
        "inv_large_note": "Sunucu bazlı ayrıntı Teknik Detaylar bölümünde.",
        "data_mount": "veri",
        "impact_title": "Etkilenen alanlar",
        "impact_none": "Sorun bulunmadı", "impact_not_checked": "Bu kontrolde incelenmedi",
        "findings_word": "bulgu",
        "config_title": "Konfigürasyon önerileri",
        "config_starting_values": "Sunucu profili (iş yükü, sunucunun PostgreSQL'e ayrılmış olup olmadığı, disk tipi) tam girilmediği için önerilen değerler bir başlangıç noktasıdır: mevcut değerlerin neden seçildiği ve gerçek iş yükü doğrulanmadan uygulanmamalıdır.",
        "config_many_connections": "max_connections = {n}: work_mem önerisi bağlantı sayısına bölündüğü için çok küçük çıkıyor. Asıl kaldıraç bağlantı sayısıdır; uygulama önünde bir connection pooler (PgBouncer gibi) ile max_connections düşürülürse sorgulara daha fazla bellek kalır.",
        "config_parts": {"DEVIATES": "{n} ayar önerilenden farklı", "NOT_ASSESSED": "{n} ayar değerlendirilemedi",
                         "FITS": "{n} ayar uygun", "NOT_APPLICABLE": "{n} ayar uygulanmaz"},
        "config_line": "{n} ayar bu sunucu için önerilen değerlerden farklı; ayrıntı teknik bölümde.",
        "config_line_na": "{n} ayar sunucu bilgisi (SSH) olmadığı için değerlendirilemedi.",
        "config_settings": "Konfigürasyon önerileri ({n} ayar)",
        "config_inputs": "Hesap en küçük sunucuya göre yapıldı: {node} ({facts}).",
        "config_cols": ["Ayar", "Şu an", "Önerilen", "Kabul edilebilir", "Neden"],
        "config_off": "kapalı", "config_cpus": "{n} CPU", "config_disk": "veri diski {v}",
        "config_restart": "↻ restart gerektirir",
        "config_assumed": "{field} girilmedi, {value} varsayıldı",
        "config_fields": {"storage_type": "disk tipi", "dedicated": "PostgreSQL'e ayrılmış olup olmadığı",
                          "workload_type": "iş yükü"},
        "config_differs": "{node} sunucusunda farklı: {value}",
        "config_disk_assumed": "Disk tipi girilmedi, {profile} varsayıldı; veri diski {observed} bildiriyor ({nodes}). Doğruysa profilde disk tipini belirtin.",
        "config_disk_conflict": "Profilde disk tipi {profile}; veri diski {observed} bildiriyor ({nodes}).",
        "config_disk_virtual": "Sanal makinede ({virt}) disk, altında SSD olsa da dönen disk görünebilir.",
        "config_commands": "Komutlar",
        "config_commands_note": "Keystone bu komutları yalnızca yazar, çalıştırmaz. Bakım penceresinde, değişikliği onaylayarak uygulayın.",
        "config_block_reload": "Reload ile etkinleşir",
        "config_block_restart": "Restart gerektirir",
        "config_block_patroni": "Patroni (DCS'teki ayarlar; reload Patroni tarafından yapılır)",
        "config_block_patroni_restart": "Patroni: restart bekleyen sunucuları yeniden başlatır",
        "config_block_unknown": "Yönetim türü profilde girilmediği için komutlar yorum satırı olarak yazıldı. Patroni kullanılıyorsa ALTER SYSTEM kullanmayın: ayar DCS'ten sapar. Profilde belirtin: UPDATE keystone.target SET cluster_manager = 'PATRONI' (ya da 'NONE').",
        "config_block_unknown_plain": "Yönetim türü profilde girilmediği için komutlar yorum satırı olarak yazıldı. Profilde belirtin: UPDATE keystone.target SET cluster_manager = 'NONE'.",
        "config_patroni_seen": "Bu kontrolde Patroni oturumları görüldü.",
        "config_patroni_config": "Cluster adı PostgreSQL'in cluster_name ayarından alındı; Patroni scope'u farklıysa değiştirin. patronictl yapılandırma dosyasını varsayılan yerde bulamazsa -c <dosya> ekleyin (örneğin -c /etc/patroni/config.yml). Bir sunucunun yerel Patroni yapılandırmasında (postgresql.parameters) tanımlı ayar DCS'teki değeri ezer: uyguladıktan sonra her sunucuda SHOW <ayar> ile doğrulayın; değer değişmediyse ayarı yerel dosyadan kaldırın ve patronictl reload çalıştırın.",
        "config_assumed_cmd": "varsayım: {items}; profili doğrulayınca kullanın",
        "config_restart_hint": "Sonra PostgreSQL'i bakım penceresinde yeniden başlatın.",
        "config_restart_list": "Restart sonrası etkin olur: {names}",
        "config_connections": "bağlantı",
        "config_calc_min": "en az", "config_calc_max": "en fazla",
        "config_calc_lower": "alt sınır", "config_calc_upper": "üst sınır",
        "config_calc_cap": "veri diskinin %{share} sınırına indirildi",
        "config_not_assessed": "{n} ayar değerlendirilemedi",
        "config_calc_checkpoints": "Son sıfırlamadan beri {total} checkpoint'ten {requested} tanesi (%{share}) WAL dolduğu için yapıldı; mevcut değer {current} × {factor} = {result}",
        "config_reason": {"no_host": "Sunucunun belleği, CPU sayısı ve diski bilinmiyor (SSH ile sunucu bilgisi toplanamadı).",
                          "no_memory": "Sunucunun belleği bilinmiyor (SSH ile sunucu bilgisi toplanamadı).",
                          "no_cpus": "CPU sayısı bilinmiyor (SSH ile sunucu bilgisi toplanamadı).",
                          "no_disk": "Veri diskinin boyutu bilinmiyor (SSH ile sunucu bilgisi toplanamadı).",
                          "few_cpus": "4'ten az CPU var; paralellik ayarları varsayılanda kalır.",
                          "windows": "Windows'ta PostgreSQL bu ayarı desteklemez; 0 kalmalı.",
                          "setting_not_collected": "Ayar bu kontrolde toplanamadı.",
                          "no_recommendation": "Bu sürüm için öneri yok."},
        "topics_title": "Alanlara göre durum",
        "topic_ok": "Sorun bulunmadı", "topic_attention": "Uyarı", "topic_critical": "Kritik",
        "topic_na": "Uygulanmaz", "advice_word": "bilgi notu",
        "topic_unknown": "Değerlendirilemedi", "topic_partial": "Kısmen değerlendirildi",
        "problems_title": "Öne çıkan sorunlar", "no_problems": "Öne çıkan bir sorun yok.",
        "open_hint": "Olası sebepler ve yapılması gerekenler için soruna tıklayın.",
        "collected_count": "{ok} / {total} başarılı",
        "why_it_matters": "Neden önemli", "what_to_do": "Ne yapılmalı", "what_happens": "Ne oluyor", "causes": "Olası sebepler",
        "system": "Sistem Bilgisi",
        "profile_title": "Sunucu profili", "profile_assumed": "belirtilmedi, varsayıldı",
        "profile_workload_type": "İş yükü", "profile_dedicated": "PostgreSQL'e ayrılmış",
        "profile_storage_type": "Disk",
        "profile_cluster_manager": "Ayar yönetimi", "profile_not_given": "belirtilmedi",
        "profile_values": {"PATRONI": "Patroni", "NONE": "ALTER SYSTEM (Patroni yok)",
                           "OLTP": "OLTP", "OLAP": "Raporlama (OLAP)", "MIXED": "Karma",
                           "SSD": "SSD", "HDD": "HDD", True: "evet", False: "hayır"},
        "nodes": "Sunucular", "node": "Sunucu", "address": "Adres", "role": "Rol",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Çalışma süresi", "os": "İşletim sistemi", "cpu": "CPU", "memory": "Bellek",
        "storage": "Disk kullanımı", "mount": "Bağlama noktası", "used": "Kullanılan",
        "total": "Toplam",
        "databases": "Veritabanları", "database": "Veritabanı", "owner": "Sahip", "size": "Boyut",
        "not_collected_here": "Bu kontrolde toplanamadı.",
        "collection_summary": "Veri toplama: {ok} / {total} başarılı",
        "more_errors": "(+{n} hata daha; teknik bölümde)",
        "collection_errors": "Hata",
        "findings": "Bulgular", "no_findings": "Bulgu yok.",
        "meaning": "Anlamı", "impact": "Etkisi", "recommendation": "Öneri",
        "observed": "Ölçülen", "subject": "Konu",
        "detail_application": "Uygulama", "detail_user": "Kullanıcı", "detail_database": "Veritabanı",
        "detail_client": "İstemci", "detail_state": "Durum", "detail_last_query": "Son gözlenen sorgu",
        "detail_transaction_start": "Transaction başlangıcı", "detail_state_change": "Bu duruma geçiş",
        "detail_captured_at": "Kanıt zamanı", "threshold": "Eşik",
        "impact_note": "Aynı sorun birden fazla alanı etkileyebilir; her alanda adıyla gösterilir.",
        "scope_note": "Yalnızca bu kontrolde değerlendirilen kurallara göre.",
        "detail_node": "Sunucu", "detail_mount": "Disk", "detail_data_directory": "Veri dizini",
        "detail_usage": "Kullanım", "detail_sync_state": "Senkronizasyon", "detail_wal_behind": "Geride kalan WAL",
        "detail_apply_delay": "Bilinçli uygulama gecikmesi",
        "detail_setting": "Ayar", "detail_table": "Tablo", "detail_live_rows": "Canlı satır",
        "detail_dead_rows": "Dead tuple", "detail_modified_rows": "Son ANALYZE'dan beri değişen",
        "detail_autovacuum_count": "Autovacuum sayısı", "detail_autoanalyze_count": "Autoanalyze sayısı",
        "detail_trigger": "Sebep", "trigger_large_table": "Büyük tablo sınırı aşıldı",
        "detail_analyze_status": "ANALYZE", "never_analyzed": "hiç çalışmamış",
        "detail_last_autovacuum": "Son autovacuum", "detail_last_vacuum": "Son vacuum",
        "detail_last_autoanalyze": "Son autoanalyze", "detail_last_analyze": "Son analyze",
        "parameters": "Parametreler", "show_all": "Tümünü göster ({n})", "detail_value": "Geçerli değer", "detail_setting_source": "Kaynak",
        "detail_connections": "Kullanılan bağlantı", "detail_max_connections": "max_connections",
        "detail_reserved_connections": "Ayrılmış", "detail_usable_connections": "Kullanılabilir",
        "detail_active": "Aktif", "detail_idle": "Boşta", "detail_idle_in_transaction": "Transaction içinde boşta", "detail_beyond_delay": "Bilinçli gecikmenin üzerindeki kısım",
        "detail_slot": "Slot", "detail_slot_type": "Slot tipi", "detail_wal_status": "WAL durumu",
        "detail_sync_names": "synchronous_standby_names",
        "detail_gid": "gid", "detail_transaction_id": "Transaction ID", "detail_prepared_at": "Hazırlanma zamanı",
        "detail_archive_mode": "archive_mode", "detail_failed_count": "Başarısız arşiv sayısı",
        "detail_archived_count": "Başarılı arşiv sayısı", "detail_last_failed_wal": "Son başarısız WAL",
        "detail_last_archived_wal": "Son arşivlenen WAL", "detail_last_failed_time": "Son hata",
        "detail_last_archived_time": "Son başarılı arşiv", "detail_stats_reset": "İstatistik sıfırlama",
        "detail_timeline": "Timeline", "detail_timeline_history_file": "History dosyası",
        "detail_timeline_started_at": "Primary olma zamanı",
        "unassessed_line": "Değerlendirilemeyen sunucu: {items}",
        "unassessed_reason": {"not_collected": "veri toplanamadı", "no_disk": "veri diski bilgisi yok",
                              "no_memory": "bellek bilgisi yok",
                              "not_in_reference": "bu major sürüm Keystone'un sürüm referansında yok",
                              "no_version": "sürüm bilgisi yok"},
        "config_host_partial": "Bilgisi eksik sunucu: {nodes}. En küçük sunucu bilinmeden bu ayarlar hesaplanmaz.",
        "reason_codes": {"nodes_unassessed": "Diğer sunucularda sorun bulunmadı; {nodes} değerlendirilemedi.",
                         "no_primary": "Toplanan sunucular arasında primary yok.",
                         "no_replicas": "Sistemde replica yok.",
                         "sync_not_configured": "Synchronous replikasyon tanımlı değil (synchronous_standby_names boş).",
                         "archiving_off": "Hiçbir sunucuda WAL arşivleme açık değil; arşivlemenin kendisini PG-BKP-002 değerlendirir.",
                         "setting_missing": "{setting} ayarı primary'de toplanamadı.",
                         "no_timeline_history": "Şu anki timeline'ın history dosyası pg_wal içinde bulunamadı.",
                         "no_nodes": "Sistemin sunucu listesi bulunamadı.",
                         "index_usage_incomplete": "{count} index erişilebilen sunucularda hiç kullanılmamış görünüyor, ama {nodes} sunucusundan index kullanımı toplanamadığı için kesin değil.",
                         "statistics_too_recent": "Index kullanım istatistikleri yeni sıfırlanmış ({databases}); değerlendirmek için en az {minimum_days} günlük veri gerekiyor.",
                         "no_index_usage": "Hiçbir sunucudan index kullanımı toplanamadı.",
                         "sequence_privilege_missing": "{count} sequence'in değeri okunamadı ({names}); izleme kullanıcısının bu sequence'ler üzerinde SELECT yetkisi yok. Yalnızca bu sequence'ler için, ilgili veritabanında: GRANT SELECT ON SEQUENCE <sequence> TO <kullanıcı>; (SELECT değeri okumaya yeter, sequence'i ilerletemez; şemadaki bütün sequence'lere toplu yetki gerekmez)."},
        "detail_sequence": "Sequence", "detail_column": "Kolon", "detail_column_type": "Kolon tipi",
        "detail_data_type": "Sequence tipi", "detail_last_value": "Son değer", "detail_limit": "Sınır",
        "detail_limit_source": "Sınırı belirleyen", "limit_source_column": "kolon tipi",
        "limit_source_sequence": "sequence tipi",
        "detail_index": "Index", "detail_index_size": "Boyut", "detail_nodes_checked": "Kontrol edilen sunucular",
        "detail_statistics_node": "En kısa istatistik", "detail_statistics_since": "İstatistik başlangıcı",
        "detail_schema": "Schema", "detail_schema_owner": "Schema sahibi", "detail_role": "Rol",
        "detail_valid_until": "Geçerlilik sonu",
        "detail_wait_event": "Beklediği", "detail_query_start": "Sorgu başlangıcı",
        "detail_started_at": "Başlama zamanı", "detail_definition": "Tanım",
        "col_severity": "Önem", "col_finding": "Bulgu", "col_pid": "PID", "col_duration": "Süre",
        "col_xid_age": "XID yaşı", "col_mxid_age": "MultiXact yaşı", "col_freeze_max_age": "autovacuum_freeze_max_age",
        "col_share": "Oran", "col_match": "Durum", "col_other_index": "Diğer index",
        "col_foreign_key": "Foreign key", "col_columns": "Kolonlar", "col_referenced": "Referans",
        "col_table_size": "Tablo boyutu", "col_usage": "Kullanım", "col_extension": "Extension",
        "col_version": "Sürüm", "col_latest": "En son sürüm", "col_behind": "Geride",
        "col_reference": "Sürüm referansı", "col_end_of_support": "Destek sonu", "col_days_left": "Kalan gün",
        "reference_source": {"SEED": "Keystone ile gelen", "FILE": "referans dosyası", "ONLINE": "internet"},
        "date_format": "%d.%m.%Y",
        "col_installed": "Kurulu sürüm", "col_available": "Paket sürümü",
        "match_same": "Aynı tanım", "match_covered": "Kapsanıyor", "col_since": "Ne kadar önce",
        "empty_value": "(boş)",
        "detail_other_definition": "Diğer index'in tanımı", "detail_analyze_trigger": "Autovacuum analyze eşiği (satır)",
        "inv_failover": "Son timeline değişimi", "inv_failover_ago": "yaklaşık {ago} önce",
        "inv_failover_never": "Gözlenmedi", "inv_failover_unknown": "Bilinmiyor", "inv_timeline": "timeline {n}",
        "billion": "milyar", "unit_TRANSACTION": "transaction", "unit_MULTIXACT": "multixact", "unit_CONNECTION": "bağlantı", "unit_ROW": "satır", "unit_RATIO": "kat", "unit_RELEASE": "sürüm", "unit_DAY": "gün",
        "results": "Kontrol sonuçları", "area": "Alan", "rule": "Kontrol", "status": "Durum", "reason": "Neden",
        "not_assessed": "Değerlendirilemeyen kontroller", "none": "Yok.",
        "collection": "Toplanan Veriler", "collector": "Veri kaynağı",
        "purpose_evidence": "Kanıt", "purpose_context": "Bağlam", "purpose": "Amaç",
        "method": "Yöntem",
        "method_text": ("Keystone hedef sisteme salt okunur bağlantıyla bağlanır ve yalnızca "
                        "sistem kataloglarını ve istatistik görünümlerini sorgular. Sistemde "
                        "nesne oluşturmaz, ayar değiştirmez, kurulum yapmaz. Sebep açıklamaları "
                        "bu tür sorunların bilinen genel sebepleridir; bu sistemdeki kesin "
                        "sebep için teknik detaylardaki bağlam bilgileri incelenmelidir."),
        "method_text_offline": ("Kanıt, müşteri tarafında çalıştırılan salt okunur script'lerle toplandı ve "
                                "Keystone'a aktarıldı; Keystone sisteme bağlanmadı. Script'ler yalnızca sistem "
                                "kataloglarını ve istatistik görünümlerini okur; nesne oluşturmaz, ayar "
                                "değiştirmez, kurulum yapmaz, tablo verisi ve sorgu metni toplamaz. Sebep "
                                "açıklamaları bu tür sorunların bilinen genel sebepleridir; bu sistemdeki kesin "
                                "sebep için teknik detaylardaki bağlam bilgileri incelenmelidir."),
        "generated": "Rapor oluşturma zamanı",
        "outcome": {"HEALTHY": "Sağlıklı", "ATTENTION_REQUIRED": "Dikkat",
                    "INSUFFICIENT_EVIDENCE": "Veri yetersiz", "ERROR": "Hata",
                    "NOT_APPLICABLE": "Uygulanmaz"},
        "severity": {"CRITICAL": "Kritik", "WARNING": "Uyarı", "INFO": "Bilgi"},
        "collection_status": {"SUCCESS": "Başarılı", "PARTIAL_SUCCESS": "Kısmen başarılı",
                              "FAILED": "Başarısız", "CONNECTION_FAILED": "Bağlantı hatası",
                              "TIMEOUT": "Zaman aşımı", "STALE": "Yarıda kaldı",
                              "NOT_COLLECTED": "Toplanamadı", "WAIT_LIMIT": "Beklenmedi"},
        "days": "gün", "hours": "saat", "minutes": "dakika",
        "reason_not_collected": "{source} bu kontrolde toplanamadı ({detail}).",
        "reason_not_collected_short": "{source} toplanamadı{status}; ayrıntı teknik bölümde.",
        "reason_stale": "{source} verisi {age} önce toplanmış; bu kontrol için en fazla {limit} eski veri kabul ediliyor.",
        "reason_missing": "{source} verisi yok.",
        "reason_reference_stale": ("Keystone'daki PostgreSQL sürüm referansı {age} önce alınmış ({as_of}); bu kontrol "
                                   "en fazla {limit} eski referans kabul ediyor, eski bilgiyle güncel sürüm "
                                   "söylenmez. Yenilemek için: python -m repository.lifecycle.release_reference --refresh (internet yoksa referans "
                                   "dosyası: --import <dosya>)."),
        "reason_reference_missing": "Keystone'da PostgreSQL sürüm referansı yok. Yüklemek için: python -m repository.lifecycle.release_reference --refresh",
    },
    "en": {
        "title": "Database Health Check Report",
        "target": "System", "date": "Date", "check_no": "Check no", "requested_by": "Requested by",
        "evidence": "Evidence", "evidence_offline": "collected offline (read-only scripts on the customer side), imported {imported}",
        "part_exec": "Executive Summary", "part_tech": "Technical Details",
        "verdict_critical": "There are problems that need immediate action.",
        "verdict_warning": "There are problems that need attention.",
        "verdict_healthy": "No problems were found in the assessed areas.",
        "verdict_none": "No check could be evaluated; data could not be collected.",
        "verdict_unassessed": "{n} check(s) could not be done.",
        "unassessed_title": "Checks not assessed",
        "unassessed_lead": "These checks could not be done; whether there is a problem is unknown.",
        "unassessed_collect": "{targets}: {source} not collected{status}",
        "unassessed_affects": "Checks affected",
        "unassessed_action": "What to do",
        "action_CONNECTION_FAILED": "Check that Keystone can connect to these servers: network access, pg_hba.conf, user and password.",
        "action_NOT_COLLECTED": "Define the connection these servers need (a HOST connection for SSH data).",
        "action_NOT_COLLECTED_offline": "Collect the missing file: for server data run the host script (host_snapshot.sh or host_snapshot_windows.ps1) on the database server; for the rest run the collector again.",
        "action_other": "The error is in the technical part (collected data); fix it and run the health check again.",
        "coverage": "Of {defined} defined checks, {total} apply to this system; {evaluated} produced a result.",
        "not_assessed_note": "{count} check(s) could not be evaluated for lack of data.",
        "not_applicable_note": "{count} check(s) do not apply to this system.",
        "count_critical": "Critical", "count_warning": "Warning",
        "count_healthy": "Healthy", "count_not_assessed": "Not assessed",
        "inventory_title": "System inventory",
        "inv_servers": "Servers", "inv_version": "PostgreSQL", "inv_cpu": "CPU", "inv_memory": "Memory",
        "inv_data": "Data", "inv_disk": "Disk",
        "inv_roles": "{primary} primary, {replica} replica", "inv_cores": "{n} cores",
        "inv_unknown_replicas": "{n} connected replica not assessed",
        "unknown_replica_cause": "{n} replica connected to the primary is not defined in Keystone and was not assessed in this check: {list}.",
        "unknown_replica_action": "Collect these servers too (run the offline script on them or define their connections); only then are their settings, disk and version assessed.",
        "inv_databases": "{n} databases", "inv_partial": "for {known} of {total} servers",
        "inv_unknown": "Not collected", "percent": "{n}%", "inv_full": "{p} used",
        "inv_data_disk": "Data disk", "inv_role": "Role", "inv_disk_unknown": "Unknown",
        "inv_large_note": "Per-server details are in the Technical Details part.",
        "data_mount": "data",
        "impact_title": "Affected areas",
        "impact_none": "No problems found", "impact_not_checked": "Not covered by this check",
        "findings_word": "finding(s)",
        "config_title": "Configuration recommendations",
        "config_starting_values": "The server profile (workload, whether the server is dedicated to PostgreSQL, disk type) is not complete, so the recommended values are a starting point: do not apply them before checking why the current values were chosen and what the real workload is.",
        "config_many_connections": "max_connections = {n}: the work_mem recommendation comes out very small because it is divided by the connections. The lever is the number of connections; with a connection pooler (PgBouncer, say) in front of the application, a lower max_connections leaves more memory for queries.",
        "config_parts": {"DEVIATES": "{n} setting(s) differ from the recommendation",
                         "NOT_ASSESSED": "{n} not assessed", "FITS": "{n} fit", "NOT_APPLICABLE": "{n} not applicable"},
        "config_line": "{n} setting(s) differ from the values recommended for this server; details in the technical part.",
        "config_line_na": "{n} setting(s) could not be assessed without server data (SSH).",
        "config_settings": "Configuration recommendations ({n} settings)",
        "config_inputs": "Calculated for the smallest server: {node} ({facts}).",
        "config_cols": ["Setting", "Current", "Recommended", "Acceptable", "Why"],
        "config_off": "off", "config_cpus": "{n} CPU(s)", "config_disk": "data disk {v}",
        "config_restart": "↻ needs a restart",
        "config_assumed": "{field} not given, {value} assumed",
        "config_fields": {"storage_type": "storage type", "dedicated": "whether the server is dedicated",
                          "workload_type": "workload"},
        "config_differs": "different on {node}: {value}",
        "config_disk_assumed": "Storage type not given, {profile} assumed; the data disk reports {observed} on {nodes}. If that is right, set the storage type in the profile.",
        "config_disk_conflict": "The profile says {profile}; the data disk reports {observed} on {nodes}.",
        "config_disk_virtual": "On a virtual machine ({virt}) a disk can appear rotating even when SSD is underneath.",
        "config_commands": "Commands",
        "config_commands_note": "Keystone only writes these commands and never runs them. Apply them in a maintenance window after review.",
        "config_block_reload": "Takes effect with a reload",
        "config_block_restart": "Needs a restart",
        "config_block_patroni": "Patroni (settings in the DCS; Patroni reloads)",
        "config_block_patroni_restart": "Patroni: restarts the servers with a pending restart",
        "config_block_unknown": "The management type is not given in the profile, so the commands are written as comments. With Patroni do not use ALTER SYSTEM: the setting drifts from the DCS. Set it in the profile: UPDATE keystone.target SET cluster_manager = 'PATRONI' (or 'NONE').",
        "config_block_unknown_plain": "The management type is not given in the profile, so the commands are written as comments. Set it in the profile: UPDATE keystone.target SET cluster_manager = 'NONE'.",
        "config_patroni_seen": "Patroni sessions were seen in this check.",
        "config_patroni_config": "The cluster name comes from PostgreSQL's cluster_name; change it if the Patroni scope differs. If patronictl does not find its configuration file, add -c <file> (for example -c /etc/patroni/config.yml). A setting in a server's local Patroni configuration (postgresql.parameters) overrides the DCS: after applying, check SHOW <setting> on every server; if the value did not change, remove the setting from the local file and run patronictl reload.",
        "config_assumed_cmd": "assumed: {items}; use after confirming the profile",
        "config_restart_hint": "Then restart PostgreSQL in a maintenance window.",
        "config_restart_list": "Take effect after a restart: {names}",
        "config_connections": "connections",
        "config_calc_min": "at least", "config_calc_max": "at most",
        "config_calc_lower": "lower limit", "config_calc_upper": "upper limit",
        "config_calc_cap": "capped at {share}% of the data disk",
        "config_not_assessed": "{n} setting(s) not assessed",
        "config_calc_checkpoints": "{requested} of {total} checkpoints since the statistics reset ({share}%) were requested because WAL filled up; current value {current} × {factor} = {result}",
        "config_reason": {"no_host": "The server's memory, CPUs and disk are unknown (no server data over SSH).",
                          "no_memory": "The server's memory is unknown (no server data over SSH).",
                          "no_cpus": "The number of CPUs is unknown (no server data over SSH).",
                          "no_disk": "The data disk size is unknown (no server data over SSH).",
                          "few_cpus": "Fewer than 4 CPUs; parallelism settings stay at their defaults.",
                          "windows": "PostgreSQL does not support this setting on Windows; it stays 0.",
                          "setting_not_collected": "The setting was not collected in this check.",
                          "no_recommendation": "No recommendation for this version."},
        "topics_title": "Status by area",
        "topic_ok": "No problems found", "topic_attention": "Warning", "topic_critical": "Critical",
        "topic_na": "Not applicable", "advice_word": "note(s)",
        "topic_unknown": "Not assessed", "topic_partial": "Partly assessed",
        "problems_title": "Main problems", "no_problems": "No problems to highlight.",
        "open_hint": "Click a problem for likely causes and what to do.",
        "collected_count": "{ok} of {total} succeeded",
        "why_it_matters": "Why it matters", "what_to_do": "What to do", "what_happens": "What is happening", "causes": "Likely causes",
        "system": "System Overview",
        "profile_title": "Server profile", "profile_assumed": "not given, assumed",
        "profile_workload_type": "Workload", "profile_dedicated": "Dedicated to PostgreSQL",
        "profile_storage_type": "Storage",
        "profile_cluster_manager": "Settings managed by", "profile_not_given": "not given",
        "profile_values": {"PATRONI": "Patroni", "NONE": "ALTER SYSTEM (no Patroni)",
                           "OLTP": "OLTP", "OLAP": "Reporting (OLAP)", "MIXED": "Mixed",
                           "SSD": "SSD", "HDD": "HDD", True: "yes", False: "no"},
        "nodes": "Servers", "node": "Server", "address": "Address", "role": "Role",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Uptime", "os": "Operating system", "cpu": "CPU", "memory": "Memory",
        "storage": "Disk usage", "mount": "Mount point", "used": "Used", "total": "Total",
        "databases": "Databases", "database": "Database", "owner": "Owner", "size": "Size",
        "not_collected_here": "Not collected in this check.",
        "collection_summary": "Data collection: {ok} of {total} succeeded",
        "more_errors": "(+{n} more; see the technical part)",
        "collection_errors": "Error",
        "findings": "Findings", "no_findings": "No findings.",
        "meaning": "Meaning", "impact": "Impact", "recommendation": "Recommendation",
        "observed": "Observed", "subject": "Subject",
        "detail_application": "Application", "detail_user": "User", "detail_database": "Database",
        "detail_client": "Client", "detail_state": "State", "detail_last_query": "Last observed query",
        "detail_transaction_start": "Transaction start", "detail_state_change": "In this state since",
        "detail_captured_at": "Evidence time", "threshold": "Threshold",
        "impact_note": "The same problem can affect more than one area; it is shown by name in each.",
        "scope_note": "Based only on the rules evaluated in this check.",
        "detail_node": "Server", "detail_mount": "Disk", "detail_data_directory": "Data directory",
        "detail_usage": "Usage", "detail_sync_state": "Sync state", "detail_wal_behind": "WAL behind",
        "detail_apply_delay": "Intended apply delay",
        "detail_setting": "Setting", "detail_table": "Table", "detail_live_rows": "Live rows",
        "detail_dead_rows": "Dead tuples", "detail_modified_rows": "Changed since last ANALYZE",
        "detail_autovacuum_count": "Autovacuum count", "detail_autoanalyze_count": "Autoanalyze count",
        "detail_trigger": "Reason", "trigger_large_table": "Large-table limit exceeded",
        "detail_analyze_status": "ANALYZE", "never_analyzed": "never run",
        "detail_last_autovacuum": "Last autovacuum", "detail_last_vacuum": "Last vacuum",
        "detail_last_autoanalyze": "Last autoanalyze", "detail_last_analyze": "Last analyze",
        "parameters": "Parameters", "show_all": "Show all ({n})", "detail_value": "Running value", "detail_setting_source": "Source",
        "detail_connections": "Connections in use", "detail_max_connections": "max_connections",
        "detail_reserved_connections": "Reserved", "detail_usable_connections": "Usable",
        "detail_active": "Active", "detail_idle": "Idle", "detail_idle_in_transaction": "Idle in transaction", "detail_beyond_delay": "Beyond the intended delay",
        "detail_slot": "Slot", "detail_slot_type": "Slot type", "detail_wal_status": "WAL status",
        "detail_sync_names": "synchronous_standby_names",
        "detail_gid": "gid", "detail_transaction_id": "Transaction ID", "detail_prepared_at": "Prepared at",
        "detail_archive_mode": "archive_mode", "detail_failed_count": "Failed archives",
        "detail_archived_count": "Archived", "detail_last_failed_wal": "Last failed WAL",
        "detail_last_archived_wal": "Last archived WAL", "detail_last_failed_time": "Last failure",
        "detail_last_archived_time": "Last success", "detail_stats_reset": "Statistics reset",
        "detail_timeline": "Timeline", "detail_timeline_history_file": "History file",
        "detail_timeline_started_at": "Became primary at",
        "unassessed_line": "Server not assessed: {items}",
        "unassessed_reason": {"not_collected": "data not collected", "no_disk": "no data disk information",
                              "no_memory": "no memory information",
                              "not_in_reference": "this major version is not in Keystone's release reference",
                              "no_version": "no version information"},
        "config_host_partial": "Server data missing: {nodes}. Without the smallest server these settings are not calculated.",
        "reason_codes": {"nodes_unassessed": "No problem on the other servers; {nodes} not assessed.",
                         "no_primary": "There is no primary among the collected servers.",
                         "no_replicas": "The system has no replicas.",
                         "sync_not_configured": "Synchronous replication is not configured (synchronous_standby_names is empty).",
                         "archiving_off": "No server archives WAL; archiving itself is judged by PG-BKP-002.",
                         "setting_missing": "{setting} was not collected on the primary.",
                         "no_timeline_history": "The history file of the current timeline is not in pg_wal.",
                         "no_nodes": "The server list of the system was not found.",
                         "index_usage_incomplete": "{count} index(es) look unused on the reachable servers, but index usage could not be collected from {nodes}, so this is not certain.",
                         "statistics_too_recent": "Index usage statistics were reset recently ({databases}); at least {minimum_days} days of data are needed.",
                         "no_index_usage": "Index usage was not collected from any server.",
                         "sequence_privilege_missing": "The value of {count} sequence(s) could not be read ({names}); the monitoring user has no SELECT on them. Grant only these, in that database: GRANT SELECT ON SEQUENCE <sequence> TO <user>; (SELECT reads the value and cannot advance the sequence; no schema-wide grant is needed)."},
        "detail_sequence": "Sequence", "detail_column": "Column", "detail_column_type": "Column type",
        "detail_data_type": "Sequence type", "detail_last_value": "Last value", "detail_limit": "Limit",
        "detail_limit_source": "Limit set by", "limit_source_column": "column type",
        "limit_source_sequence": "sequence type",
        "detail_index": "Index", "detail_index_size": "Size", "detail_nodes_checked": "Servers checked",
        "detail_statistics_node": "Shortest statistics", "detail_statistics_since": "Statistics since",
        "detail_schema": "Schema", "detail_schema_owner": "Schema owner", "detail_role": "Role",
        "detail_valid_until": "Valid until",
        "detail_wait_event": "Waiting for", "detail_query_start": "Statement start",
        "detail_started_at": "Started at", "detail_definition": "Definition",
        "col_severity": "Severity", "col_finding": "Finding", "col_pid": "PID", "col_duration": "Duration",
        "col_xid_age": "XID age", "col_mxid_age": "MultiXact age", "col_freeze_max_age": "autovacuum_freeze_max_age",
        "col_share": "Share", "col_match": "Match", "col_other_index": "Other index",
        "col_foreign_key": "Foreign key", "col_columns": "Columns", "col_referenced": "References",
        "col_table_size": "Table size", "col_usage": "Usage", "col_extension": "Extension",
        "col_version": "Version", "col_latest": "Latest release", "col_behind": "Behind",
        "col_reference": "Release reference", "col_end_of_support": "End of support", "col_days_left": "Days left",
        "reference_source": {"SEED": "shipped with Keystone", "FILE": "reference file", "ONLINE": "internet"},
        "date_format": "%Y-%m-%d",
        "col_installed": "Installed", "col_available": "Package",
        "match_same": "Same definition", "match_covered": "Covered", "col_since": "How long ago",
        "empty_value": "(empty)",
        "detail_other_definition": "Other index's definition", "detail_analyze_trigger": "Autovacuum analyze trigger (rows)",
        "inv_failover": "Last timeline change", "inv_failover_ago": "about {ago} ago",
        "inv_failover_never": "None observed", "inv_failover_unknown": "Unknown", "inv_timeline": "timeline {n}",
        "billion": "billion", "unit_TRANSACTION": "transactions", "unit_MULTIXACT": "multixacts", "unit_CONNECTION": "connections", "unit_ROW": "rows", "unit_RATIO": "times", "unit_RELEASE": "releases", "unit_DAY": "days",
        "results": "Check results", "area": "Area", "rule": "Check", "status": "Status", "reason": "Reason",
        "not_assessed": "Checks not assessed", "none": "None.",
        "collection": "Collected Data", "collector": "Data source",
        "purpose_evidence": "Evidence", "purpose_context": "Context", "purpose": "Purpose",
        "method": "Method",
        "method_text": ("Keystone connects to the target system with read-only access and only "
                        "queries system catalogs and statistics views. It creates no objects, "
                        "changes no settings and installs nothing on the system. Causes describe "
                        "the usual reasons for such problems; for the exact cause in this system "
                        "see the context in the technical details."),
        "method_text_offline": ("The evidence was collected on the customer side with read-only scripts and "
                                "imported into Keystone; Keystone did not connect to the system. The scripts "
                                "only read system catalogs and statistics views; they create no objects, "
                                "change no settings, install nothing and collect no table data or query "
                                "texts. Causes describe the usual reasons for such problems; for the exact "
                                "cause in this system see the context in the technical details."),
        "generated": "Report generated",
        "outcome": {"HEALTHY": "Healthy", "ATTENTION_REQUIRED": "Attention",
                    "INSUFFICIENT_EVIDENCE": "Insufficient data", "ERROR": "Error",
                    "NOT_APPLICABLE": "Not applicable"},
        "severity": {"CRITICAL": "Critical", "WARNING": "Warning", "INFO": "Info"},
        "collection_status": {"SUCCESS": "Success", "PARTIAL_SUCCESS": "Partial",
                              "FAILED": "Failed", "CONNECTION_FAILED": "Connection failed",
                              "TIMEOUT": "Timed out", "STALE": "Interrupted",
                              "NOT_COLLECTED": "Not collected", "WAIT_LIMIT": "Not waited for"},
        "days": "days", "hours": "hours", "minutes": "minutes",
        "reason_not_collected": "{source} could not be collected in this check ({detail}).",
        "reason_not_collected_short": "{source} not collected{status}; details in the technical part.",
        "reason_stale": "{source} data was collected {age} ago; at most {limit} old data is accepted for this check.",
        "reason_missing": "No {source} data.",
        "reason_reference_stale": ("Keystone's PostgreSQL release reference was taken {age} ago ({as_of}); this "
                                   "check accepts a reference at most {limit} old, and no version is called "
                                   "current on old data. To refresh: python -m repository.lifecycle.release_reference --refresh (without internet, a "
                                   "reference file: --import <file>)."),
        "reason_reference_missing": "Keystone has no PostgreSQL release reference. To load it: python -m repository.lifecycle.release_reference --refresh",
    },
}


# -----------------------------------------------------------------------------
# Data
# -----------------------------------------------------------------------------

def latest_health_check_id(conn, target_id):
    row = conn.execute(
        "SELECT max(health_check_id) AS id FROM keystone.health_check "
        "WHERE target_id = %s AND status = 'COMPLETED'", (target_id,)).fetchone()
    if row["id"] is None:
        raise ValueError(f"Target {target_id} has no completed health check.")
    return row["id"]


def load_dictionary_texts(conn):
    """Rule, topic and category texts for every language, plus rule topics and categories."""
    rule_texts = {}
    for r in conn.execute("SELECT rule_id, language_code, text_type, text FROM keystone.rule_text"):
        rule_texts.setdefault(r["rule_id"], {}).setdefault(r["language_code"], {})[r["text_type"]] = r["text"]

    topics = {}
    for r in conn.execute(
            "SELECT d.topic_key, d.display_order, t.language_code, t.name "
            "FROM keystone.dictionary_topic d JOIN keystone.dictionary_topic_text t USING (topic_key)"):
        topic = topics.setdefault(r["topic_key"], {"order": r["display_order"], "text": {}})
        topic["text"][r["language_code"]] = {"name": r["name"]}

    categories = {}
    for r in conn.execute(
            "SELECT d.category_key, d.display_order, t.language_code, t.name, t.description "
            "FROM keystone.dictionary_impact_category d "
            "JOIN keystone.dictionary_impact_category_text t USING (category_key)"):
        category = categories.setdefault(r["category_key"], {"order": r["display_order"], "text": {}})
        category["text"][r["language_code"]] = {"name": r["name"], "description": r["description"]}

    rule_categories = {}
    for r in conn.execute("SELECT rule_id, category_key FROM keystone.rule_impact_category"):
        rule_categories.setdefault(r["rule_id"], set()).add(r["category_key"])

    return {"rule_texts": rule_texts, "topics": topics, "categories": categories,
            "rule_categories": rule_categories}


def load_report_data(conn, health_check_id):
    """Everything the report shows, read once; context data as of the check's end."""
    check = conn.execute(
        "SELECT hc.*, t.name AS target_name, t.provider, t.environment "
        "FROM keystone.health_check hc JOIN keystone.target t USING (target_id) "
        "WHERE hc.health_check_id = %s", (health_check_id,)).fetchone()
    if check is None:
        raise ValueError(f"Health check {health_check_id} does not exist.")
    finished = check["finished_at"] or datetime.now(timezone.utc)
    # Context only from what this check collected (filtered below by its collections);
    # target clocks may differ from the repository's, so the window is generous and
    # the collection status, not the time, decides.
    since = check["started_at"] - timedelta(days=1)
    as_of = finished + timedelta(seconds=CLOCK_SKEW_TOLERANCE_SECONDS)

    results = conn.execute(
        """
        SELECT ad.assessment_key, rd.rule_id, rd.rule_key, rd.name AS rule_name, rd.topic_key,
               res.outcome, res.max_severity, res.reason, res.unassessed, ar.assessment_run_id,
               COALESCE(res.thresholds_used, (
                   SELECT jsonb_agg(jsonb_build_object('severity', th.severity,
                                                       'value', th.threshold_value,
                                                       'unit', th.threshold_unit))
                   FROM keystone.rule_threshold th WHERE th.rule_id = rd.rule_id
               )) AS thresholds,
               COALESCE(res.parameters_used, (
                   SELECT jsonb_object_agg(rp.parameter_key, jsonb_build_object(
                              'value', rp.parameter_value, 'unit', rp.parameter_unit))
                   FROM keystone.rule_parameter rp WHERE rp.rule_id = rd.rule_id
               )) AS parameters
        FROM keystone.assessment_run ar
        JOIN keystone.assessment_definition ad ON ad.assessment_id = ar.assessment_id
        JOIN keystone.assessment_result res ON res.assessment_run_id = ar.assessment_run_id
        JOIN keystone.rule_definition rd ON rd.rule_id = res.rule_id
        WHERE ar.health_check_id = %s
        ORDER BY rd.rule_key
        """, (health_check_id,)).fetchall()

    findings = conn.execute(
        """
        SELECT f.finding_id, f.rule_id, f.severity, f.title, f.finding_text, f.recommendation,
               f.observed_value, f.observed_unit, f.subject_type, f.subject_identifier, f.details,
               f.template_values
        FROM keystone.finding f
        JOIN keystone.assessment_run ar ON ar.assessment_run_id = f.assessment_run_id
        WHERE ar.health_check_id = %s
        ORDER BY f.finding_id
        """, (health_check_id,)).fetchall()

    collections = conn.execute(
        "SELECT c.target_id, c.collector_key, c.purpose, c.status, c.status_message, "
        "t.name AS target_name "
        "FROM keystone.health_check_collection c JOIN keystone.target t USING (target_id) "
        "WHERE c.health_check_id = %s ORDER BY c.purpose DESC, c.collector_key, t.name",
        (health_check_id,)).fetchall()

    # Servers: the target itself if it is a NODE, else its NODE children.
    nodes = conn.execute(
        """
        SELECT t.target_id, t.name, ii.server_address, ii.server_port, ii.server_version,
               tc.host AS connection_host, tc.port AS connection_port,
               ii.in_recovery, ii.postmaster_start_time,
               hs.hostname, hs.os_name, hs.os_version, hs.logical_cpu_count,
               hs.memory_total_bytes, hs.captured_at AS host_captured_at, hs.virtualization,
               cs.setting_value AS data_directory
        FROM keystone.target t
        LEFT JOIN postgresql.instance_inventory ii
            ON ii.target_id = t.target_id AND ii.last_collected_at BETWEEN %s AND %s
        LEFT JOIN LATERAL (
            SELECT c.host, c.port FROM keystone.target_connection c
            WHERE c.target_id = t.target_id AND c.is_active AND c.connection_purpose <> 'HOST'
            ORDER BY c.connection_id LIMIT 1
        ) tc ON TRUE
        LEFT JOIN LATERAL (
            SELECT * FROM postgresql.host_snapshot h
            WHERE h.target_id = t.target_id AND h.captured_at BETWEEN %s AND %s
            ORDER BY h.captured_at DESC LIMIT 1
        ) hs ON TRUE
        LEFT JOIN LATERAL (
            SELECT c.setting_value FROM postgresql.configuration_snapshot c
            WHERE c.target_id = t.target_id AND c.setting_name = 'data_directory'
              AND c.captured_at BETWEEN %s AND %s
            ORDER BY c.captured_at DESC LIMIT 1
        ) cs ON TRUE
        WHERE (t.parent_target_id = %s AND t.target_type = 'NODE' AND t.is_active)
           OR (t.target_id = %s AND t.target_type = 'NODE')
        ORDER BY t.target_id
        """, (since, as_of, since, as_of, since, as_of,
              check["target_id"], check["target_id"])).fetchall()

    storage = conn.execute(
        """
        SELECT t.target_id, t.name AS node_name, s.device, s.mount_point, s.used_bytes, s.total_bytes,
               s.available_bytes, s.rotational
        FROM keystone.target t
        JOIN LATERAL (
            SELECT max(captured_at) AS captured_at FROM postgresql.storage_snapshot
            WHERE target_id = t.target_id AND captured_at BETWEEN %s AND %s
        ) last ON last.captured_at IS NOT NULL
        JOIN postgresql.storage_snapshot s
            ON s.target_id = t.target_id AND s.captured_at = last.captured_at
        WHERE (t.parent_target_id = %s AND t.target_type = 'NODE' AND t.is_active)
           OR (t.target_id = %s AND t.target_type = 'NODE')
        ORDER BY t.target_id, s.mount_point
        """, (since, as_of, check["target_id"], check["target_id"])).fetchall()

    databases = conn.execute(
        """
        SELECT d.database_name, d.database_owner, d.database_size_bytes
        FROM postgresql.database_snapshot d
        WHERE d.target_id = %s
          AND d.captured_at = (SELECT max(captured_at) FROM postgresql.database_snapshot
                               WHERE target_id = %s AND captured_at BETWEEN %s AND %s)
          AND NOT COALESCE(d.is_template, FALSE)
        ORDER BY d.database_size_bytes DESC NULLS LAST, d.database_name
        """, (check["target_id"], check["target_id"], since, as_of)).fetchall()

    wal_status = conn.execute(
        """
        SELECT w.target_id, w.captured_at, w.in_recovery, w.timeline_id, w.timeline_started_at
        FROM keystone.target t
        JOIN LATERAL (
            SELECT * FROM postgresql.wal_status_snapshot s
            WHERE s.target_id = t.target_id AND s.captured_at BETWEEN %s AND %s
            ORDER BY s.captured_at DESC LIMIT 1
        ) w ON TRUE
        WHERE (t.parent_target_id = %s AND t.target_type = 'NODE' AND t.is_active)
           OR (t.target_id = %s AND t.target_type = 'NODE')
        """, (since, as_of, check["target_id"], check["target_id"])).fetchall()

    dictionary = load_dictionary_texts(conn)
    config = conn.execute(
        """
        SELECT cr.* FROM keystone.config_recommendation cr
        JOIN keystone.assessment_result res USING (assessment_result_id)
        JOIN keystone.assessment_run ar USING (assessment_run_id)
        WHERE ar.health_check_id = %s
        ORDER BY cr.config_recommendation_id
        """, (health_check_id,)).fetchall()
    # A hint only (review 2026-11-09): Patroni's own sessions seen by this check.
    patroni_seen = conn.execute(
        """
        SELECT EXISTS (SELECT 1 FROM postgresql.activity_snapshot a JOIN keystone.target t USING (target_id)
                       WHERE (t.target_id = %s OR t.parent_target_id = %s)
                         AND a.captured_at BETWEEN %s AND %s AND a.application_name ILIKE 'patroni%%')
        """, (check["target_id"], check["target_id"], since, as_of)).fetchone()["exists"]
    # Patroni's scope is PostgreSQL's cluster_name unless changed; for patronictl restart.
    cluster_name = conn.execute(
        """
        SELECT cs.setting_value FROM postgresql.configuration_snapshot cs
        JOIN keystone.target t USING (target_id)
        WHERE (t.target_id = %s OR t.parent_target_id = %s) AND cs.setting_name = 'cluster_name'
          AND cs.captured_at BETWEEN %s AND %s AND cs.setting_value <> ''
        ORDER BY cs.captured_at DESC LIMIT 1
        """, (check["target_id"], check["target_id"], since, as_of)).fetchone()
    # Streams from the primary (pg_stat_replication) of this check, and every name Keystone knows its
    # servers by: a replica streaming from a server Keystone does not know was not assessed (pilot
    # hc111, 2026-11-11: an async replica at another address, inventory said "0 replica").
    replicas_seen = conn.execute(
        """
        SELECT DISTINCT ON (r.target_id, r.client_addr, r.application_name)
               r.target_id, r.captured_at, r.application_name, host(r.client_addr) AS client_addr,
               r.state, r.sync_state
        FROM postgresql.replica_status_snapshot r
        JOIN keystone.target t USING (target_id)
        WHERE (t.target_id = %s OR t.parent_target_id = %s)
          AND r.captured_at = (SELECT max(s.captured_at) FROM postgresql.replication_status_snapshot s
                               WHERE s.target_id = r.target_id AND s.captured_at BETWEEN %s AND %s)
        ORDER BY r.target_id, r.client_addr, r.application_name
        """, (check["target_id"], check["target_id"], since, as_of)).fetchall()
    identities = {r["identity"] for r in conn.execute(
        """
        SELECT i.identity FROM keystone.target_identity i JOIN keystone.target t USING (target_id)
        WHERE t.target_id = %s OR t.parent_target_id = %s
        """, (check["target_id"], check["target_id"]))}
    config_reasons = {}
    for r in conn.execute("SELECT setting_key, language_code, text FROM keystone.config_setting_text "
                          "WHERE provider = %s AND text_type = 'REASON'", (check["provider"],)):
        config_reasons.setdefault(r["setting_key"], {})[r["language_code"]] = r["text"]
    conn.commit()

    collected = {(c["target_id"], c["collector_key"]) for c in collections
                 if c["status"] in ("SUCCESS", "PARTIAL_SUCCESS")}
    nodes = [only_collected(n, collected) for n in nodes]
    storage = [s_ for s_ in storage if (s_["target_id"], "PG_HOST_SNAPSHOT") in collected]
    if (check["target_id"], "PG_DATABASE_INVENTORY") not in collected:
        databases = []
    wal_status = [w for w in wal_status if (w["target_id"], "PG_WAL_STATUS") in collected]
    known = identities | {str(n.get("server_address") or "").split("/")[0] for n in nodes} - {""}
    unknown_replicas = [r for r in replicas_seen if (r["target_id"], "PG_REPLICATION_STATUS") in collected
                        and r["client_addr"] and r["client_addr"] not in known]

    return {"check": check, "results": results, "findings": findings,
            "collections": collections, "nodes": nodes, "storage": storage,
            "databases": databases, "wal_status": wal_status, "as_of": finished,
            "config": config, "config_reasons": config_reasons, "patroni_seen": patroni_seen,
            "unknown_replicas": unknown_replicas,
            "cluster_name": cluster_name["setting_value"] if cluster_name else None, **dictionary}


NODE_CONTEXT = {
    "PG_INSTANCE_INVENTORY": ("server_address", "server_port", "server_version", "in_recovery",
                              "postmaster_start_time"),
    "PG_HOST_SNAPSHOT": ("hostname", "os_name", "os_version", "logical_cpu_count",
                         "memory_total_bytes", "host_captured_at"),
    "PG_CONFIGURATION_SNAPSHOT": ("data_directory",),
}


def only_collected(node, collected):
    """A node row without the parts this check did not collect (no older data shown as current)."""
    node = dict(node)
    for key, fields in NODE_CONTEXT.items():
        if (node["target_id"], key) not in collected:
            node.update({field: None for field in fields})
    return node


# -----------------------------------------------------------------------------
# Formatting
# -----------------------------------------------------------------------------

def e(value):
    return html.escape("" if value is None else str(value))


def fmt_time(value):
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def fmt_bytes(value):
    if value is None:
        return ""
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def fmt_uptime(start, as_of, t):
    if not start:
        return ""
    return fmt_duration((as_of - start).total_seconds(), t)


def fmt_quantity(value, unit, t):
    """A measured value or threshold in readable form: '5 dakika', '1.5 milyar transaction'."""
    if value is None:
        return ""
    value = float(value)
    if unit == "SECOND":
        return fmt_duration(value, t)
    if unit == "BYTE":
        return fmt_bytes(value)
    if unit == "PERCENT":
        return t["percent"].format(n=f"{value:g}")
    if unit in ("TRANSACTION", "MULTIXACT") and value >= 1e9:
        return f"{value / 1e9:g} {t['billion']} {t['unit_' + unit]}"
    number = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return f"{number} {t.get('unit_' + (unit or ''), unit or '')}".strip()


def fmt_observed(value, unit, t=None):
    if value is None:
        return ""
    if t is not None:
        return fmt_quantity(value, unit, t)
    number = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return f"{number} {unit or ''}".strip()


def threshold_values(result, t):
    """{'warning': '5 dakika', 'critical': '15 dakika'} from the thresholds used."""
    values = {}
    for th in result.get("thresholds") or []:
        values[th["severity"].lower()] = fmt_quantity(th["value"], th["unit"], t)
    return values


def healthy_text(data, result, lang, t):
    """The rule's HEALTHY text with its limits filled from the thresholds used."""
    text = rule_text(data, result["rule_id"], lang, "HEALTHY")
    values = threshold_values(result, t)
    return re.sub(r"\{(warning|critical)\}", lambda m: values.get(m.group(1), m.group(0)), text)


def threshold_line(result, t):
    values = threshold_values(result, t)
    parts = [f"{t['severity'][sev]} ≥ {values[sev.lower()]}" for sev in ("WARNING", "CRITICAL")
             if sev.lower() in values]
    return f"{t['threshold']}: " + " · ".join(parts) if parts else ""


def fmt_duration(seconds, t):
    """Rough human duration: '4 gün 17 saat', '10 dakika'."""
    seconds = int(max(seconds, 0))
    days, hours, minutes = seconds // 86400, seconds % 86400 // 3600, seconds % 3600 // 60
    if days:
        return f"{days} {t['days']}" + (f" {hours} {t['hours']}" if hours else "")
    if hours:
        return f"{hours} {t['hours']}" + (f" {minutes} {t['minutes']}" if minutes else "")
    return f"{max(minutes, 1)} {t['minutes']}"


REASON_PATTERN = re.compile(
    r"^(?P<source>[A-Z0-9_]+): (?:Evidence is stale\. Age=(?P<age>[\d.]+)s, MaxAge=(?P<max>\d+)s"
    r"|(?P<missing>Required evidence is not available\.))$")


# Reasons an evaluator gives itself: "SOURCE: [code] English message {values}".
REASON_CODE_PATTERN = re.compile(r"^[A-Z0-9_]+: \[(?P<code>[a-z_]+)\] .*?(?P<values>\{.*\})?$")


def explain_reason(reason, data, t, short=False):
    """Engine reason in plain words; says when this check failed to collect the source.

    short: without the technical error message (executive part).
    """
    coded = REASON_CODE_PATTERN.match(reason or "")
    if coded and coded.group("code") in t["reason_codes"]:
        try:
            values = json.loads(coded.group("values") or "{}")
            return t["reason_codes"][coded.group("code")].format(**values)
        except (ValueError, KeyError):
            return reason
    match = REASON_PATTERN.match(reason or "")
    if not match:
        return reason or ""
    source = match.group("source")
    if source in REFERENCE_SOURCES:                # held by Keystone, not collected
        if match.group("missing"):
            return t["reason_reference_missing"]
        age = float(match.group("age"))
        as_of = data["check"]["finished_at"] or datetime.now(timezone.utc)
        return t["reason_reference_stale"].format(
            age=fmt_duration(age, t), limit=fmt_duration(int(match.group("max")), t),
            as_of=(as_of - timedelta(seconds=age)).strftime(t["date_format"]))
    failed = [c for c in data["collections"] if c["collector_key"] == source
              and c["status"] not in ("SUCCESS", "PARTIAL_SUCCESS")]
    if failed:
        c = failed[0]
        if short:
            return t["reason_not_collected_short"].format(source=source, status=status_suffix(c["status"], t))
        message = first_line(c["status_message"]) or "-"
        detail = message if c["status"] == "NOT_COLLECTED" else (
            f'{t["collection_status"].get(c["status"], c["status"])}: {message}')
        return t["reason_not_collected"].format(source=source, detail=detail)
    if match.group("missing"):
        return t["reason_missing"].format(source=source)
    return t["reason_stale"].format(source=source, age=fmt_duration(float(match.group("age")), t),
                                    limit=fmt_duration(int(match.group("max")), t))


def first_sentence(text):
    """First sentence of a Dictionary text, for the short executive view."""
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s", text)
    return text[:match.start()] if match else text


def list_items(text):
    """Items of a list text ('- item' per line, V034); None for plain text."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if lines and all(line.startswith("- ") for line in lines):
        return [line[2:].strip() for line in lines]
    return None


def render_text(text, short=False):
    """A Dictionary text as HTML: lists as bullets, plain text escaped (first sentence if short)."""
    items = list_items(text)
    if items:
        return '<ul class="items">' + "".join(f"<li>{e(item)}</li>" for item in items) + "</ul>"
    return e(first_sentence(text) if short else text)


def rule_text(data, rule_id, lang, text_type, default=""):
    """Dictionary text in the report language, falling back to English."""
    texts = data["rule_texts"].get(rule_id, {})
    for code in (lang, FALLBACK_LANGUAGE):
        if text_type in texts.get(code, {}):
            return texts[code][text_type]
    return default


def localized(entry, lang, field):
    for code in (lang, FALLBACK_LANGUAGE):
        if code in entry["text"]:
            return entry["text"][code][field]
    return ""


def advisory(result):
    """A rule whose findings are all INFO: recommendations, not problems (ADR-0017)."""
    return result["outcome"] == "ATTENTION_REQUIRED" and result.get("max_severity") == "INFO"


def summarize(data):
    # A rule that does not apply here (no replicas, say) is not a check done; it is noted apart.
    results = [r for r in data["results"] if r["outcome"] != "NOT_APPLICABLE"]
    counts = {"total": len(results), "healthy": 0, "attention": 0, "not_assessed": 0,
              "critical": 0, "warning": 0,
              "not_applicable": len(data["results"]) - len(results), "defined": len(data["results"])}
    for r in results:
        # Recommendations (INFO only) are no risk: the executive part counts the rule as healthy.
        if r["outcome"] == "HEALTHY" or advisory(r):
            counts["healthy"] += 1
        elif r["outcome"] == "ATTENTION_REQUIRED":
            counts["attention"] += 1
        else:
            counts["not_assessed"] += 1
    # Tiles count checks, so they add up to the total; findings are counted per problem card.
    for r in results:
        if r["outcome"] == "ATTENTION_REQUIRED" and not advisory(r):
            counts["critical" if r["max_severity"] == "CRITICAL" else "warning"] += 1
    counts["findings"] = sum(1 for f in data["findings"] if f["severity"] != "INFO")
    counts["evaluated"] = counts["healthy"] + counts["attention"]

    if counts["critical"]:
        verdict = "critical"
    elif counts["attention"] or counts["findings"]:
        verdict = "warning"
    elif counts["evaluated"]:
        verdict = "healthy"
    else:
        verdict = "none"
    return counts, verdict


def impact_summary(data):
    """Per category: the problems (rules with findings, worst severity) and whether it was checked."""
    evaluated = {r["rule_id"] for r in data["results"]
                 if r["outcome"] in ("HEALTHY", "ATTENTION_REQUIRED")}
    # Not assessed, or assessed without some nodes: the area is never "no problems" (review 2026-11-09).
    incomplete = {r["rule_id"] for r in data["results"]
                  if r["outcome"] in ("INSUFFICIENT_EVIDENCE", "ERROR") or r.get("unassessed")}
    summary = {key: {"problems": {}, "checked": False, "incomplete": False} for key in data["categories"]}
    for rule_id, keys in data["rule_categories"].items():
        for key in keys:
            if rule_id in evaluated and key in summary:
                summary[key]["checked"] = True
            if rule_id in incomplete and key in summary:
                summary[key]["incomplete"] = True
    for f in data["findings"]:
        if f["severity"] == "INFO":
            continue                         # recommendations are not problems of an area
        for key in data["rule_categories"].get(f["rule_id"], ()):
            if key in summary:
                problems = summary[key]["problems"]
                current = problems.get(f["rule_id"])
                if current is None or SEVERITY_ORDER.get(f["severity"], 9) < SEVERITY_ORDER.get(current, 9):
                    problems[f["rule_id"]] = f["severity"]
    return summary


def topic_summary(data):
    """Per topic present in the check: status and the rules that need attention."""
    topics = {}
    for r in data["results"]:
        key = r["topic_key"] or "_OTHER"
        topic = topics.setdefault(key, {"results": [], "status": "ok"})
        topic["results"].append(r)
    for topic in topics.values():
        severities = [r["max_severity"] for r in topic["results"] if r["max_severity"]]
        outcomes = ["HEALTHY" if advisory(r) else r["outcome"] for r in topic["results"]
                    if r["outcome"] != "NOT_APPLICABLE"]
        if not outcomes:
            topic["status"] = "na"
        elif "CRITICAL" in severities:
            topic["status"] = "critical"
        elif "ATTENTION_REQUIRED" in outcomes:
            topic["status"] = "attention"
        elif "HEALTHY" not in outcomes:
            topic["status"] = "unknown"
        elif any(o != "HEALTHY" for o in outcomes):
            topic["status"] = "partial"          # never "no problems" while a rule was not assessed
        elif (any(r["rule_key"] == CONFIG_RULE for r in topic["results"])
              and config_counts(data)["NOT_ASSESSED"]):
            topic["status"] = "partial"          # settings the recommendations could not cover
    order = lambda key: data["topics"].get(key, {}).get("order", 999)   # noqa: E731
    return sorted(topics.items(), key=lambda item: order(item[0]))


def findings_by_rule(data):
    """[(result, [findings])] for rules with findings, most severe first."""
    grouped = {}
    for f in data["findings"]:
        grouped.setdefault(f["rule_id"], []).append(f)
    results = {r["rule_id"]: r for r in data["results"]}
    items = [(results[rule_id], fs) for rule_id, fs in grouped.items() if rule_id in results]
    items.sort(key=lambda item: (min(SEVERITY_ORDER.get(f["severity"], 9) for f in item[1]),
                                 item[0]["rule_key"]))
    return items


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------

STYLE = """
:root{--ink:#1d2430;--muted:#5b6575;--line:#d9dee5;--soft:#f4f6f9;--accent:#1f4e79;
--crit:#b42318;--crit-bg:#fdecea;--warn:#93600a;--warn-bg:#fdf3df;--ok:#1e6b3a;--ok-bg:#e7f4ec;
--na:#5b6575;--na-bg:#eef0f3;--crit-bar:#d92d20;--warn-bar:#e0a100;--ok-bar:#3a8f5c}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:980px;margin:0 auto;padding:40px 32px 64px}
header{border-bottom:3px solid var(--accent);padding-bottom:18px;margin-bottom:8px}
.brand{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-size:26px;margin:6px 0 14px}
.part{font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);
font-weight:700;margin:40px 0 0;padding:8px 0;border-bottom:2px solid var(--accent)}
h2{font-size:19px;margin:30px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px}
.meta{display:flex;flex-wrap:wrap;gap:6px 28px;color:var(--muted);font-size:14px}
.meta b{color:var(--ink);font-weight:600}
.verdict{padding:16px 18px;border-radius:8px;font-size:18px;font-weight:600;margin:22px 0 10px}
.v-critical{background:var(--crit-bg);color:var(--crit)}
.v-warning{background:var(--warn-bg);color:var(--warn)}
.v-healthy{background:var(--ok-bg);color:var(--ok)}
.v-none{background:var(--na-bg);color:var(--na)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.tile .n{font-size:24px;font-weight:700;line-height:1.2}
.tile .l{color:var(--muted);font-size:13px}
.note{color:var(--muted);font-size:14px}
.inv{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:8px 0}
.inv>div{background:var(--soft);border-radius:8px;padding:10px 14px}
.inv .l{color:var(--muted);font-size:13px}
.inv .v{font-size:19px;font-weight:700;line-height:1.3}
.inv .s{color:var(--muted);font-size:12px}
.meter{display:inline-block;width:60px;height:8px;background:var(--line);border-radius:4px;margin-right:8px;vertical-align:middle;overflow:hidden}
.meter i{display:block;height:100%}
.m-ok{background:var(--ok-bar)}.m-warn{background:var(--warn-bar)}.m-crit{background:var(--crit-bar)}
.impact{display:grid;grid-template-columns:minmax(120px,170px) 1fr;gap:10px 14px;align-items:baseline}
.impact .name{font-weight:600}
.impact .val{font-size:14px;display:flex;flex-wrap:wrap;gap:6px 16px}
.problem .badge{margin-right:6px}
.topic{display:grid;grid-template-columns:200px 130px 1fr;gap:6px 14px;align-items:baseline;
padding:9px 0;border-bottom:1px solid var(--line)}
.topic .name{font-weight:600}
.topic>.badge{justify-self:start}
.rules{list-style:none;margin:0;padding:0}
.rules li{position:relative;padding:1px 0 1px 18px}
.rules li::before{content:"";position:absolute;left:2px;top:.6em;width:8px;height:8px;border-radius:50%;
background:var(--ok-bar);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.rules li.r-critical::before{background:var(--crit-bar)}
.rules li.r-warning::before{background:var(--warn-bar)}
.rules li.r-unknown::before{background:var(--na)}
.rules li.r-info::before{background:var(--accent)}
.rules li.r-na{color:var(--muted)}
.cmd{background:var(--soft);border-radius:4px;padding:8px 10px;margin:6px 0;font:12px/1.5 Consolas,monospace;white-space:pre-wrap;word-break:break-word}
.rules li.r-na::before{background:none;border:1.5px solid var(--na);box-sizing:border-box}
details.card>summary,details.section>summary{cursor:pointer;list-style:none}
details>summary::-webkit-details-marker{display:none}
details.card>summary h3::before,details.section>summary h2::before{content:"▸";color:var(--muted);width:12px}
details.card[open]>summary h3::before,details.section[open]>summary h2::before{content:"▾"}
details.card:not([open]) h3{margin:0}
details.section>summary h2{display:flex;gap:10px;align-items:baseline}
.card .lead{font-size:14px;margin:4px 0 0 22px}
table{width:100%;border-collapse:collapse;font-size:14px;margin:6px 0 10px}
th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1px solid var(--line);padding:7px 8px;background:var(--soft)}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}
td.num,th.num{text-align:right;white-space:nowrap}
.badge{display:inline-block;border-radius:4px;padding:1px 8px;font-size:12px;font-weight:600;white-space:nowrap}
.b-CRITICAL,.b-ERROR,.b-critical{background:var(--crit-bg);color:var(--crit)}
.b-WARNING,.b-ATTENTION_REQUIRED,.b-attention{background:var(--warn-bg);color:var(--warn)}
.b-INFO,.b-INSUFFICIENT_EVIDENCE,.b-unknown,.b-partial,.b-NOT_APPLICABLE,.b-na{background:var(--na-bg);color:var(--na)}
.b-HEALTHY,.b-SUCCESS,.b-ok{background:var(--ok-bg);color:var(--ok)}
.b-FAILED,.b-CONNECTION_FAILED,.b-TIMEOUT,.b-STALE{background:var(--crit-bg);color:var(--crit)}
.b-PARTIAL_SUCCESS,.b-WAIT_LIMIT{background:var(--warn-bg);color:var(--warn)}
.b-NOT_COLLECTED{background:var(--na-bg);color:var(--na)}
.card{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px;margin:10px 0}
.card.CRITICAL{border-left-color:var(--crit)}
.card.unknown{border-left-color:var(--na)}
.verdict .sub{font-size:14px;font-weight:400;margin-left:8px}
.card h3{margin:0 0 6px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card dl{margin:6px 0 0;display:grid;grid-template-columns:minmax(110px,150px) 1fr;gap:4px 12px}
.card dt{color:var(--muted);font-size:13px;font-weight:600}
.card dd{margin:0}
.items{margin:0;padding-left:18px}.items li{margin:1px 0}
.more summary{cursor:pointer;color:var(--accent);font-size:14px;margin-top:8px}
.ftable{font-size:13.5px;margin:12px 0 4px}.ftable th{font-size:12.5px}
.ftable code{font:12px Consolas,monospace;color:var(--muted);white-space:pre-wrap;word-break:break-word}
.instance{background:var(--soft);border-radius:4px;padding:8px 10px;margin-top:8px;font-size:14px}
.instance code{font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-word}
.facts{color:var(--muted);font-size:13px;margin-top:4px}
.rule{color:var(--muted);font-size:12px;font-family:Consolas,monospace;white-space:nowrap}
.tabs>input{position:absolute;opacity:0;pointer-events:none}
.tabs>label{display:inline-block;padding:10px 18px;margin:24px 4px 0 0;border:1px solid var(--line);
border-bottom:none;border-radius:8px 8px 0 0;background:var(--soft);color:var(--muted);cursor:pointer;
font-size:13px;letter-spacing:.1em;text-transform:uppercase;font-weight:700}
.tabs>input:focus-visible+label{outline:2px solid var(--accent);outline-offset:2px}
.tabs>input:checked+label{background:#fff;color:var(--accent);border-color:var(--accent);
box-shadow:inset 0 3px 0 var(--accent)}
.tabs>.panel{display:none;border-top:2px solid var(--accent)}
#tab-exec:checked~.panel-exec,#tab-tech:checked~.panel-tech{display:block}
.tabs .part{display:none}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media (max-width:640px){main{padding:24px 16px 48px}h1{font-size:22px}
table{display:block;overflow-x:auto}.topic{grid-template-columns:1fr auto}.topic .rules{grid-column:1/-1}
.impact{grid-template-columns:1fr}.card dl{grid-template-columns:1fr}}
@media print{main{padding:0;max-width:none}h2{break-after:avoid}.card,tr,.topic{break-inside:avoid}
details::details-content{content-visibility:visible;display:block}
details.card>summary h3::before,details.section>summary h2::before{content:none}
.tabs>label{display:none}.tabs>.panel{display:block!important;border-top:none}.tabs .part{display:block}
.panel-tech{break-before:page}body{font-size:12px}
.meter i,.badge{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
"""


def table(headers, rows, numeric=()):
    # Numeric columns: header right-aligned like the values under it.
    head = "".join(f'<th class="num">{e(h)}</th>' if i in numeric else f"<th>{e(h)}</th>"
                   for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(
            f'<td class="num">{cell}</td>' if i in numeric else f"<td>{cell}</td>"
            for i, cell in enumerate(row)) + "</tr>"
        for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def badge(code, label):
    return f'<span class="badge b-{e(code)}">{e(label)}</span>'


def render_header(data, t):
    check = data["check"]
    meta = [(t["target"], check["target_name"]), (t["date"], fmt_time(check["started_at"])),
            (t["check_no"], check["health_check_id"])]
    if check["requested_by"]:
        meta.append((t["requested_by"], check["requested_by"]))
    if check.get("source") == "OFFLINE":
        # Offline: the date above is the capture; when it was imported is said apart.
        meta.append((t["evidence"], t["evidence_offline"].format(
            imported=fmt_time(check["imported_at"]) if check.get("imported_at") else "-")))
    return ('<header><div class="brand">Keystone</div>'
            f"<h1>{e(t['title'])}</h1><div class=\"meta\">"
            + "".join(f"<span>{e(label)}: <b>{e(value)}</b></span>" for label, value in meta)
            + "</div></header>")


def short_version(version):
    """'17.10 (Ubuntu 17.10-1.pgdg24.04+1)' -> '17.10'."""
    return (version or "").split(" ")[0]


# Executive inventory: a row per server up to this many, beyond that totals only.
INVENTORY_TABLE_LIMIT = 10
DATA_DISK_RULE = "PG-CAP-001"
DEFAULT_DISK_LIMITS = {"warning": 80, "critical": 90}


def data_disk(node, storage):
    """The node's data disk, chosen exactly like the data disk rule does."""
    mounts = [s_ for s_ in storage if s_["target_id"] == node["target_id"] and s_["total_bytes"]]
    return data_mount(node.get("data_directory"), mounts)


def shown_mounts(storage, data_mounts):
    """One row per node and device: the data mount if it is there, else the shortest mount point.

    df -a also lists bind mounts of the same filesystem (/etc/hosts in a container, say).
    """
    chosen = {}
    for s_ in storage:
        key = (s_["target_id"], s_.get("device") or s_["mount_point"])
        current = chosen.get(key)
        if (current is None or id(s_) in data_mounts
                or (id(current) not in data_mounts and len(s_["mount_point"]) < len(current["mount_point"]))):
            chosen[key] = s_
    return [s_ for s_ in storage if chosen.get((s_["target_id"], s_.get("device") or s_["mount_point"])) is s_]


def disk_limits(data):
    """Meter colours follow the data disk rule's thresholds used in this check."""
    limits = dict(DEFAULT_DISK_LIMITS)
    for result in data.get("results", []):
        if result["rule_key"] == DATA_DISK_RULE:
            for th in result.get("thresholds") or []:
                limits[th["severity"].lower()] = float(th["value"])
    return limits


def disk_percent(disk):
    return round(usage_percent(disk["used_bytes"], disk.get("available_bytes"), disk["total_bytes"]))


def fmt_used_of(used, total):
    used_text, size_text = fmt_bytes(used), fmt_bytes(total)
    if used_text.split()[-1] == size_text.split()[-1]:          # "7.8 / 13.1 GB"
        used_text = used_text.rsplit(" ", 1)[0]
    return f"{used_text} / {size_text}"


def os_text(node):
    """'Ubuntu 24.04.4 LTS' from the host snapshot; the OS, not PostgreSQL's build string."""
    text = node.get("os_name") or ""
    if node.get("os_version") and node["os_version"] not in text:
        text = f"{text} {node['os_version']}".strip()
    return text


def or_unknown(value, t):
    """A cell value, or a muted 'unknown' when it was not collected (no SSH, say)."""
    if value in (None, ""):
        return f'<span class="note">{e(t["inv_disk_unknown"])}</span>'
    return e(value)


def host_port(host, port):
    """'10.0.0.5:5432', '[::1]:5432' (IPv6 in brackets, so the port is not read as part of it)."""
    return f"[{host}]:{port}" if ":" in str(host) else f"{host}:{port}"


def address_cell(node):
    """The address Keystone connects to; the server's own (NAT, Docker, proxy) as a tooltip if different."""
    registered = (host_port(node["connection_host"], node["connection_port"] or 5432)
                  if node.get("connection_host") else "")
    reported = host_port(node["server_address"], node["server_port"]) if node.get("server_address") else ""
    if registered and reported and registered != reported:
        return f'<span title="{e(reported)}">{e(registered)}</span>'
    return e(registered or reported)


def version_cell(version):
    """'17.10' shown; the package build ('Ubuntu 17.10-1.pgdg24.04+1') only on hover."""
    if not version:
        return ""
    return f'<span title="{e(version)}">{e(short_version(version))}</span>'


def role_of(node, t):
    if node["in_recovery"] is None:
        return ""
    return t["role_replica"] if node["in_recovery"] else t["role_primary"]


def disk_cell(disk, limits, t):
    if disk is None:
        return f'<span class="note">{e(t["inv_disk_unknown"])}</span>'
    pct = disk_percent(disk)
    level = ("crit" if pct >= limits.get("critical", 101)
             else "warn" if pct >= limits.get("warning", 101) else "ok")
    return (f'<span class="meter"><i class="m-{level}" style="width:{min(pct, 100)}%"></i></span>'
            f'{e(fmt_used_of(disk["used_bytes"], disk["total_bytes"]))} · '
            f'{e(t["percent"].format(n=pct))}')


def failover_item(data, t):
    """(label, value, sub) for the last failover of the primary collected in this check, or None."""
    primaries = [w for w in data.get("wal_status", [])
                 if w["in_recovery"] is False and w["timeline_id"] is not None]
    if not primaries:
        return None
    primary = max(primaries, key=lambda w: w["captured_at"])
    timeline = t["inv_timeline"].format(n=primary["timeline_id"])
    if primary["timeline_id"] == 1:
        return t["inv_failover"], t["inv_failover_never"], timeline
    started = primary["timeline_started_at"]
    if started is None:
        return t["inv_failover"], t["inv_failover_unknown"], timeline
    ago = t["inv_failover_ago"].format(ago=fmt_duration((primary["captured_at"] - started).total_seconds(), t))
    return t["inv_failover"], ago, f"{timeline} · {fmt_time(started)}"


def render_inventory(data, t):
    """Executive view of the estate: totals and a row per server when few. Displays, never judges."""
    nodes = data["nodes"]
    known = [n for n in nodes if n["server_version"] is not None]
    hosts = [n for n in nodes if n["logical_cpu_count"] is not None or n["memory_total_bytes"] is not None]
    disks = {n["target_id"]: d for n in nodes if (d := data_disk(n, data["storage"])) is not None}
    total = len(nodes)

    def partial(count):
        return t["inv_partial"].format(known=count, total=total) if total and count < total else ""

    items = []
    if total:
        primary = sum(1 for n in known if n["in_recovery"] is False)
        replica = sum(1 for n in known if n["in_recovery"])
        roles = t["inv_roles"].format(primary=primary, replica=replica) if known else ""
        if data.get("unknown_replicas"):
            roles += " · " + t["inv_unknown_replicas"].format(n=len(data["unknown_replicas"]))
        items.append((t["inv_servers"], str(total), roles))
        versions = sorted({short_version(n["server_version"]) for n in known})
        items.append((t["inv_version"], ", ".join(versions) or t["inv_unknown"], partial(len(known))))
        if hosts:
            cores = sum(n["logical_cpu_count"] or 0 for n in hosts)
            memory = sum(n["memory_total_bytes"] or 0 for n in hosts)
            items.append((t["inv_cpu"], t["inv_cores"].format(n=cores), partial(len(hosts))))
            items.append((t["inv_memory"], fmt_bytes(memory), partial(len(hosts))))
    failover = failover_item(data, t)
    if failover:
        items.append(failover)
    if data["databases"]:
        size = sum(d["database_size_bytes"] or 0 for d in data["databases"])
        items.append((t["inv_data"], fmt_bytes(size), t["inv_databases"].format(n=len(data["databases"]))))
    # Data disks when known: other mounts (/boot, backups) would distort the ratio.
    disk_rows = list(disks.values()) or data["storage"]
    if disk_rows:
        used = sum(s_["used_bytes"] or 0 for s_ in disk_rows)
        size = sum(s_["total_bytes"] or 0 for s_ in disk_rows)
        disk_nodes = len({s_["target_id"] for s_ in disk_rows})
        available = (sum(s_["available_bytes"] for s_ in disk_rows)
                     if all(s_.get("available_bytes") is not None for s_ in disk_rows) else None)
        share = usage_percent(used, available, size)
        pct = t["inv_full"].format(p=t["percent"].format(n=round(share))) if share is not None else ""
        items.append((t["inv_data_disk"] if disks else t["inv_disk"], fmt_used_of(used, size),
                      " · ".join(x for x in (pct, partial(disk_nodes)) if x)))
    if not items:
        return ""

    parts = [f"<h2>{e(t['inventory_title'])}</h2><div class=\"inv\">"
             + "".join(f'<div><div class="l">{e(label)}</div><div class="v">{e(value)}</div>'
                       f'<div class="s">{e(sub)}</div></div>' for label, value, sub in items)
             + "</div>"]
    shown = [n for n in nodes if n["server_version"] is not None or n["target_id"] in disks
             or n in hosts]
    if shown and len(nodes) <= INVENTORY_TABLE_LIMIT:
        rows = [[e(n["name"]), e(role_of(n, t)), or_unknown(os_text(n), t),
                 or_unknown(t["inv_cores"].format(n=n["logical_cpu_count"]) if n["logical_cpu_count"] else "", t),
                 or_unknown(fmt_bytes(n["memory_total_bytes"]) if n["memory_total_bytes"] else "", t),
                 disk_cell(disks.get(n["target_id"]), disk_limits(data), t)] for n in nodes]
        parts.append(table([t["inv_servers"], t["inv_role"], t["os"], t["inv_cpu"], t["inv_memory"],
                            t["inv_data_disk"]], rows, numeric=(3, 4)))
    elif shown:
        parts.append(f'<p class="note">{e(t["inv_large_note"])}</p>')

    return "".join(parts)


def render_impact_chart(data, lang, t):
    """Areas and the problems affecting them, by name: the same problem is recognisable in each area."""
    summary = impact_summary(data)
    names = {r["rule_id"]: r["rule_name"] for r in data["results"]}
    rows = []
    for key, entry in sorted(data["categories"].items(), key=lambda item: item[1]["order"]):
        s_ = summary[key]
        name = localized(entry, lang, "name")
        if s_["problems"]:
            ordered = sorted(s_["problems"].items(), key=lambda item: SEVERITY_ORDER.get(item[1], 9))
            value = "".join(
                f'<span class="problem">{badge(sev, t["severity"].get(sev, sev))}'
                f'{e(rule_text(data, rule_id, lang, "NAME", names.get(rule_id, "")))}</span>'
                for rule_id, sev in ordered)
        else:
            if s_["checked"] and s_["incomplete"]:
                value = badge("partial", t["topic_partial"])
            elif s_["checked"]:
                value = badge("ok", t["impact_none"])
            elif s_["incomplete"]:
                value = badge("unknown", t["topic_unknown"])
            else:
                value = badge("unknown", t["impact_not_checked"])
        rows.append(f'<div class="name" title="{e(localized(entry, lang, "description"))}">'
                    f'{e(name)}</div><div class="val">{value}</div>')
    note = ('<p class="note">' + e(t["scope_note"])
            + (f' {e(t["impact_note"])}' if data["findings"] else "") + "</p>")
    return f"<h2>{e(t['impact_title'])}</h2><div class=\"impact\">{''.join(rows)}</div>" + note


def config_topic_item(data, t):
    """One line for the configuration recommendations: how many differ, how many could not be assessed."""
    counts = config_counts(data)
    texts = []
    if counts["DEVIATES"]:
        texts.append(t["config_line"].format(n=counts["DEVIATES"]))
    if counts["NOT_ASSESSED"]:
        texts.append(t["config_line_na"].format(n=counts["NOT_ASSESSED"]))
    if not texts:
        return ("ok", e(config_summary(counts, t, ("FITS", "NOT_APPLICABLE"))))
    cls = "info" if counts["DEVIATES"] else "unknown"
    return (cls, f"<b>{e(t['config_title'])}</b>: " + e(" · ".join(texts)))


def render_topics(data, lang, t):
    """Per topic one item per rule: problems first, then rules not assessed, then what was fine."""
    order = {"ATTENTION_REQUIRED": 0, "INSUFFICIENT_EVIDENCE": 1, "ERROR": 1, "HEALTHY": 2,
             "NOT_APPLICABLE": 3}
    rows = []
    for key, topic in topic_summary(data):
        entry = data["topics"].get(key)
        name = localized(entry, lang, "name") if entry else key
        status = topic["status"]
        items = []
        for r in sorted(topic["results"], key=lambda r: order.get(r["outcome"], 3)):
            rule_name = rule_text(data, r["rule_id"], lang, "NAME", r["rule_name"])
            if r["rule_key"] == CONFIG_RULE and data.get("config"):
                items.append(config_topic_item(data, t))
                continue
            # (bullet colour, text): severity shows in the bullet and in words, texts stay aligned.
            if advisory(r):
                count = sum(1 for f in data["findings"] if f["rule_id"] == r["rule_id"])
                items.append(("info", f"<b>{e(rule_name)}</b> ({count} {e(t['advice_word'])}): "
                              + e(first_sentence(rule_text(data, r["rule_id"], lang, "MEANING")))))
            elif r["outcome"] == "ATTENTION_REQUIRED":
                count = sum(1 for f in data["findings"] if f["rule_id"] == r["rule_id"])
                severity = r["max_severity"] or "WARNING"
                label = t["severity"].get(severity, severity).lower()
                partial = unassessed_line(r, t)
                items.append((severity.lower(),
                              f"<b>{e(rule_name)}</b> ({count} {e(t['findings_word'])}, {e(label)}): "
                              + e(first_sentence(rule_text(data, r["rule_id"], lang, "MEANING")))
                              + (f' <span class="facts">{e(partial)}</span>' if partial else "")))
            elif r["outcome"] == "HEALTHY":
                # The rule's own scoped statement: no claim beyond what was checked.
                items.append(("ok", e(healthy_text(data, r, lang, t))))
            elif r["outcome"] == "NOT_APPLICABLE":
                reason = explain_reason(r.get("reason"), data, t, short=True)
                items.append(("na", f"{e(rule_name)} ({e(t['outcome']['NOT_APPLICABLE'].lower())})"
                              + (f": {e(reason)}" if reason else "")))
            else:
                reason = explain_reason(r.get("reason"), data, t, short=True)
                items.append(("unknown", f"<b>{e(rule_name)}</b> ({e(t['topic_unknown'].lower())})"
                              + (f": {e(reason)}" if reason else "")))
        rows.append(f'<div class="topic"><span class="name">{e(name)}</span>'
                    f'{badge(status, t["topic_" + status])}<ul class="rules">'
                    + "".join(f'<li class="r-{cls}">{text}</li>' for cls, text in items) + "</ul></div>")
    return (f"<h2>{e(t['topics_title'])}</h2>" + "".join(rows)
            + f'<p class="note">{e(t["scope_note"])}</p>')


def problem_rows(data, rule_id, lang, t, findings, short, meaning=True):
    """What is happening, likely causes, why it matters, what to do: shared by both parts."""
    causes = rule_text(data, rule_id, lang, "CAUSES")
    rows = [(t["what_happens"] if short else t["meaning"],
             render_text(rule_text(data, rule_id, lang, "MEANING"), short) if meaning else ""),
            (t["causes"], render_text(causes) if causes else ""),
            (t["why_it_matters"] if short else t["impact"],
             render_text(rule_text(data, rule_id, lang, "IMPACT"), short)),
            (t["what_to_do"] if short else t["recommendation"],
             render_text(rule_text(data, rule_id, lang, "RECOMMENDATION",
                                   findings[0]["recommendation"]), short))]
    return "".join(f"<dt>{e(label)}</dt><dd>{html_}</dd>" for label, html_ in rows if html_)


def render_main_problems(data, lang, t):
    cards = []
    for result, findings in findings_by_rule(data):
        worst = min((f["severity"] for f in findings), key=lambda s: SEVERITY_ORDER.get(s, 9))
        if worst == "INFO":
            continue                         # recommendations stay out of the executive cards
        name = rule_text(data, result["rule_id"], lang, "NAME", result["rule_name"])
        meaning = first_sentence(rule_text(data, result["rule_id"], lang, "MEANING"))
        # Closed by default: name, severity and one sentence; causes and steps on demand.
        cards.append(
            f'<details class="card {e(worst)}"><summary><h3>{badge(worst, t["severity"].get(worst, worst))}'
            f"{e(name)}<span class=\"note\">{len(findings)} {e(t['findings_word'])}</span></h3>"
            f'<div class="lead">{e(meaning)}</div></summary><dl>'
            + problem_rows(data, result["rule_id"], lang, t, findings, short=True, meaning=False)
            + "</dl></details>")
    return f"<h2>{e(t['problems_title'])}</h2>" + (
        f'<p class="note">{e(t["open_hint"])}</p>' + "".join(cards) if cards
        else f'<p class="note">{e(t["no_problems"])}</p>')


def unassessed_groups(data, lang, t):
    """[(cause, action, [rule names])]: checks not assessed, grouped by their cause.

    One collection failing (a node, a privilege) often stops many checks; it is listed once.
    """
    groups = {}
    for r in data["results"]:
        if r["outcome"] in ("HEALTHY", "ATTENTION_REQUIRED", "NOT_APPLICABLE"):
            continue
        name = rule_text(data, r["rule_id"], lang, "NAME", r["rule_name"])
        match = REASON_PATTERN.match(r.get("reason") or "")
        failed = [c for c in data["collections"] if match and c["collector_key"] == match.group("source")
                  and c["status"] not in ("SUCCESS", "PARTIAL_SUCCESS")] if match else []
        if failed:
            status = failed[0]["status"]
            targets = ", ".join(sorted({c["target_name"] for c in failed}))
            cause = t["unassessed_collect"].format(
                targets=targets, source=match.group("source"), status=status_suffix(status, t))
            key = (targets, status)
            offline = data["check"].get("source") == "OFFLINE" and status == "NOT_COLLECTED"
            action = t["action_NOT_COLLECTED_offline"] if offline else t.get("action_" + status, t["action_other"])
        else:
            cause = explain_reason(r.get("reason"), data, t) or name
            key = ("cause", cause)                 # the same missing source is one item
            action = ""
        group = groups.setdefault(key, {"cause": cause, "action": action, "rules": [],
                                        "source": match.group("source") if failed else None})
        group["rules"].append(name)
    # Settings the configuration recommendations could not cover for lack of server data.
    host_settings = sum(1 for r in data.get("config") or []
                        if r["status"] == "NOT_ASSESSED" and r["reason_code"] in HOST_REASONS)
    if host_settings:
        label = t["config_settings"].format(n=host_settings)
        host_group = next((g for g in groups.values() if g.get("source") == "PG_HOST_SNAPSHOT"), None)
        if host_group is None:
            host_group = groups.setdefault(("config", "host"), {
                "cause": t["config_reason"]["no_memory"],
                "action": t["action_NOT_COLLECTED_offline" if data["check"].get("source") == "OFFLINE"
                            else "action_NOT_COLLECTED"],
                "rules": [], "source": "PG_HOST_SNAPSHOT"})
        host_group["rules"].append(label)
    return list(groups.values())


def render_unassessed(data, lang, t):
    """Executive card for checks not done: draws attention without being a finding."""
    groups = unassessed_groups(data, lang, t)
    unknown = data.get("unknown_replicas") or []
    if not groups and not unknown:
        return ""
    # The same number as the verdict: checks not assessed (settings without data are listed, not counted).
    count = summarize(data)[0]["not_assessed"]
    items = []
    if unknown:
        listed = ", ".join(f"{r['client_addr']} ({', '.join(x for x in (r['application_name'], r['state'], r['sync_state']) if x)})"
                           for r in unknown)
        items.append(f"<li><b>{e(t['unknown_replica_cause'].format(n=len(unknown), list=listed))}</b>"
                     f'<div class="facts">{e(t["unassessed_action"])}: {e(t["unknown_replica_action"])}</div></li>')
    for g in groups:
        affected = ", ".join(g["rules"])
        item = f"<b>{e(g['cause'])}</b>"
        if g["rules"] != [g["cause"]]:
            item += f'<div class="facts">{e(t["unassessed_affects"])}: {e(affected)}</div>'
        if g["action"]:
            item += f'<div class="facts">{e(t["unassessed_action"])}: {e(g["action"])}</div>'
        items.append(f"<li>{item}</li>")
    return (f'<details class="card unknown"><summary><h3>{badge("unknown", t["topic_unknown"])}'
            f'{e(t["unassessed_title"])}<span class="note">{count}</span></h3>'
            f'<div class="lead">{e(t["unassessed_lead"])}</div></summary>'
            f'<ul class="items">{"".join(items)}</ul></details>')


def first_line(text):
    """First line of a collector error; PostgreSQL adds LINE/caret lines that belong in the details."""
    return next((line.strip() for line in (text or "").splitlines() if line.strip()), "")


def status_suffix(status, t):
    """' (failed)' after 'not collected'; nothing for NOT_COLLECTED, which would repeat the verb."""
    if status == "NOT_COLLECTED":
        return ""
    return f' ({t["collection_status"].get(status, status).lower()})'


def shorten(text, limit=140):
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def render_executive(data, lang, t):
    counts, verdict = summarize(data)
    tiles = [(counts["critical"], t["count_critical"]), (counts["warning"], t["count_warning"]),
             (counts["healthy"], t["count_healthy"]), (counts["not_assessed"], t["count_not_assessed"])]
    coverage = e(t["coverage"].format(**counts)) + (
        f" · {e(t['not_assessed_note'].format(count=counts['not_assessed']))}"
        if counts["not_assessed"] else "")   # the checks that do not apply are in the first sentence
    collections = data["collections"]
    ok = sum(1 for c in collections if c["status"] in ("SUCCESS", "PARTIAL_SUCCESS"))
    if collections and ok < len(collections):
        errors = sorted({first_line(c["status_message"]) for c in collections
                         if c["status"] not in ("SUCCESS", "PARTIAL_SUCCESS") and c["status_message"]})
        coverage += ("<br>" + e(t["collection_summary"].format(ok=ok, total=len(collections)))
                     + (f" · {e(t['collection_errors'])}: {e(shorten(errors[0]))}"
                        + (f" {e(t['more_errors'].format(n=len(errors) - 1))}" if len(errors) > 1 else "")
                        if errors else ""))
    return (f'<div class="part">{e(t["part_exec"])}</div>'
            f'<div class="verdict v-{verdict}">{e(t["verdict_" + verdict])}'
            + (f' <span class="sub">{e(t["verdict_unassessed"].format(n=counts["not_assessed"]))}</span>'
               if counts["not_assessed"] and verdict != "none" else "") + "</div>"
            + f'<p class="note">{coverage}</p><div class="tiles">'
            + "".join(f'<div class="tile"><div class="n">{n}</div><div class="l">{e(label)}</div></div>'
                      for n, label in tiles)
            + "</div>" + render_main_problems(data, lang, t) + render_unassessed(data, lang, t)
            + render_inventory(data, t)
            + render_impact_chart(data, lang, t) + render_topics(data, lang, t))


def profile_line(profile, t):
    """'Workload: OLTP (not given, assumed) · ...' from the profile this check used; '' for older checks."""
    if not profile:
        return ""
    items = []
    for field in ("workload_type", "dedicated", "storage_type", "cluster_manager"):
        entry = profile.get(field)
        if not entry:
            continue
        if entry["value"] is None:                       # no default: not given, never assumed
            items.append(e(f'{t["profile_" + field]}: {t["profile_not_given"]}'))
            continue
        text = f'{t["profile_" + field]}: {t["profile_values"].get(entry["value"], entry["value"])}'
        if entry.get("assumed"):
            text += f' ({t["profile_assumed"]})'
        items.append(e(text))
    return f'<p><b>{e(t["profile_title"])}</b> · ' + " · ".join(items) + "</p>" if items else ""


def render_system(data, t):
    parts = [f"<h2>{e(t['system'])}</h2>", profile_line(data["check"].get("target_profile"), t)]
    missing = f'<p class="note">{e(t["not_collected_here"])}</p>'
    if data["nodes"]:
        rows = []
        for n in data["nodes"]:
            if n["server_version"] is None and n["os_name"] is None:
                rows.append([e(n["name"]), f'<span class="note">{e(t["not_collected_here"])}</span>',
                             "", "", "", "", "", ""])
                continue
            role = "" if n["in_recovery"] is None else (
                t["role_replica"] if n["in_recovery"] else t["role_primary"])
            rows.append([e(n["name"]), address_cell(n),
                         e(role), version_cell(n["server_version"]),
                         e(fmt_uptime(n["postmaster_start_time"], data["as_of"], t)),
                         or_unknown(os_text(n), t),
                         or_unknown(n["logical_cpu_count"], t),
                         or_unknown(fmt_bytes(n["memory_total_bytes"]) if n["memory_total_bytes"] else "", t)])
        parts.append(f"<h3>{e(t['nodes'])}</h3>" + table(
            [t["node"], t["address"], t["role"], t["version"], t["up_since"], t["os"], t["cpu"],
             t["memory"]], rows, numeric=(6, 7)))
    if data["storage"]:
        data_mounts = {id(d) for n in data["nodes"] if (d := data_disk(n, data["storage"]))}
        parts.append(f"<h3>{e(t['storage'])}</h3>" + table(
            [t["node"], t["mount"], t["used"], t["total"], "%"],
            [[e(s["node_name"]),
              e(s["mount_point"]) + (f' <span class="note">({e(t["data_mount"])})</span>'
                                     if id(s) in data_mounts else ""),
              e(fmt_bytes(s["used_bytes"])),
              e(fmt_bytes(s["total_bytes"])),
              e(t["percent"].format(n=disk_percent(s)) if s["total_bytes"] else "")]
             for s in shown_mounts(data["storage"], data_mounts)], numeric=(2, 3, 4)))
    parts.append(f"<h3>{e(t['databases'])}</h3>")
    if data["databases"]:
        parts.append(table(
            [t["database"], t["owner"], t["size"]],
            [[e(d["database_name"]), e(d["database_owner"]), e(fmt_bytes(d["database_size_bytes"]))]
             for d in data["databases"]], numeric=(2,)))
    else:
        parts.append(missing)
    return "".join(parts)


DETAIL_LABELS = (("node", "detail_node"), ("table", "detail_table"), ("live_rows", "detail_live_rows"),
                 ("dead_rows", "detail_dead_rows"), ("modified_rows", "detail_modified_rows"),
                 ("autovacuum_count", "detail_autovacuum_count"),
                 ("autoanalyze_count", "detail_autoanalyze_count"), ("trigger", "detail_trigger"),
                 ("analyze_status", "detail_analyze_status"),
                 ("setting", "detail_setting"), ("value", "detail_value"),
                 ("setting_source", "detail_setting_source"),
                 ("connections", "detail_connections"), ("max_connections", "detail_max_connections"),
                 ("reserved_connections", "detail_reserved_connections"),
                 ("usable_connections", "detail_usable_connections"), ("active", "detail_active"),
                 ("idle", "detail_idle"), ("idle_in_transaction", "detail_idle_in_transaction"),
                 ("mount_point", "detail_mount"),
                 ("data_directory", "detail_data_directory"), ("usage", "detail_usage"),
                 ("slot_name", "detail_slot"), ("slot_type", "detail_slot_type"),
                 ("wal_status", "detail_wal_status"), ("synchronous_standby_names", "detail_sync_names"),
                 ("application", "detail_application"), ("user", "detail_user"),
                 ("database", "detail_database"), ("client_addr", "detail_client"),
                 ("state", "detail_state"), ("sync_state", "detail_sync_state"),
                 ("wal_behind", "detail_wal_behind"), ("apply_delay", "detail_apply_delay"),
                 ("beyond_delay", "detail_beyond_delay"), ("gid", "detail_gid"),
                 ("transaction_id", "detail_transaction_id"), ("archive_mode", "detail_archive_mode"),
                 ("failed_count", "detail_failed_count"), ("last_failed_wal", "detail_last_failed_wal"),
                 ("archived_count", "detail_archived_count"),
                 ("last_archived_wal", "detail_last_archived_wal"), ("timeline_id", "detail_timeline"),
                 ("timeline_history_file", "detail_timeline_history_file"),
                 ("index", "detail_index"), ("index_size", "detail_index_size"),
                 ("nodes_checked", "detail_nodes_checked"), ("statistics_node", "detail_statistics_node"),
                 ("schema", "detail_schema"), ("schema_owner", "detail_schema_owner"),
                 ("role", "detail_role"), ("sequence", "detail_sequence"), ("column", "detail_column"),
                 ("data_type", "detail_data_type"), ("column_type", "detail_column_type"),
                 ("last_value", "detail_last_value"), ("limit", "detail_limit"),
                 ("limit_source", "detail_limit_source"), ("wait_event", "detail_wait_event"),
                 ("analyze_trigger", "detail_analyze_trigger"), ("definition", "detail_definition"),
                 ("other_definition", "detail_other_definition"))


TIME_LABELS = (("transaction_start", "detail_transaction_start"),
               ("state_change", "detail_state_change"),
               ("last_autovacuum", "detail_last_autovacuum"), ("last_vacuum", "detail_last_vacuum"),
               ("last_autoanalyze", "detail_last_autoanalyze"), ("last_analyze", "detail_last_analyze"),
               ("prepared_at", "detail_prepared_at"), ("last_failed_time", "detail_last_failed_time"),
               ("last_archived_time", "detail_last_archived_time"), ("stats_reset", "detail_stats_reset"),
               ("timeline_started_at", "detail_timeline_started_at"),
               ("statistics_since", "detail_statistics_since"), ("valid_until", "detail_valid_until"),
               ("query_start", "detail_query_start"), ("started_at", "detail_started_at"),
               ("captured_at", "detail_captured_at"))


def fmt_clock(value):
    """ISO time from finding details -> 'YYYY-MM-DD HH:MM:SS' (local to the repository)."""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


# Units of pg_settings values and their size in bytes or seconds.
SETTING_BYTES = {"B": 1, "kB": 1024, "8kB": 8192, "16kB": 16384, "MB": 1024 ** 2, "GB": 1024 ** 3}
SETTING_SECONDS = {"ms": 0.001, "s": 1, "min": 60, "h": 3600, "d": 86400}


def setting_value_text(value, unit, t):
    """'32768' with unit '8kB' -> '32768 (256.0 MB)'; other values unchanged."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return value
    if unit in SETTING_BYTES:
        return f"{value} ({fmt_bytes(number * SETTING_BYTES[unit])})"
    if unit in SETTING_SECONDS and number > 0:
        return f"{value} ({fmt_duration(number * SETTING_SECONDS[unit], t)})"
    return value


# Counts get thousands separators; identifiers such as pid stay as they are.
COUNT_VALUES = {"dead_rows", "modified_rows", "xid_age", "mxid_age", "connections", "usable",
                "connection_count", "last_value", "limit", "changed_rows", "freeze_max_age"}
# Durations in seconds read as '2 saat 5 dakika' in the report language.
DURATION_VALUES = {"age_seconds", "since_seconds", "statistics_seconds", "running_seconds"}
SIZE_VALUES = {"index_size", "size_bytes"}
DATE_VALUES = {"end_of_support"}


def template_value_text(key, value, t=None):
    if key in DATE_VALUES and t is not None and isinstance(value, str):
        try:
            return datetime.fromisoformat(value).strftime(t["date_format"])
        except ValueError:
            return value
    if key in COUNT_VALUES and isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    if key in DURATION_VALUES and t is not None and isinstance(value, (int, float)):
        return fmt_duration(value, t)
    if key in SIZE_VALUES and isinstance(value, (int, float)):
        return fmt_bytes(value)
    return value


def finding_sentence(f, data, lang):
    """The finding in the report language from its stored values; the stored English text otherwise."""
    values = f.get("template_values")
    if not values:
        return f["finding_text"]
    text_type = "FINDING_ALT" if values.get("_alt") else "FINDING"
    template = data["rule_texts"].get(f["rule_id"], {}).get(lang, {}).get(text_type)
    if not template:
        return f["finding_text"]
    t = TEXTS.get(lang)
    try:
        return template.format(**{k: template_value_text(k, v, t) for k, v in values.items()})
    except (KeyError, IndexError, ValueError):
        return f["finding_text"]


# Findings shown open per rule; the rest stays in the report behind "show all".
FINDINGS_SHOWN = 10


# ----------------------------------------------------------------------------- findings as tables

def finding_fields(f, t):
    """A finding's values for table cells: readable details, template values, the measured value."""
    details = dict(f["details"] or {})
    for key, value in details.items():           # 5000.0 connections are 5000 (pilot hc111)
        if isinstance(value, float) and value.is_integer():
            details[key] = int(value)
    if details.get("setting_unit") and details.get("value") is not None:
        details["value"] = setting_value_text(details["value"], details["setting_unit"], t)
    if details.get("never_analyzed"):
        details["analyze_status"] = t["never_analyzed"]
    for key in ("live_rows", "dead_rows", "modified_rows", "analyze_trigger", "last_value", "limit"):
        if isinstance(details.get(key), (int, float)) and not isinstance(details.get(key), bool):
            details[key] = f"{details[key]:,}"
    if details.get("limit_source"):
        details["limit_source"] = t.get("limit_source_" + details["limit_source"], details["limit_source"])
    if details.get("index_size_bytes") is not None:
        details["index_size"] = fmt_bytes(details["index_size_bytes"])
    if details.get("match"):
        details["match"] = t["match_" + details["match"]]
    if details.get("client_hostname"):
        details["client_addr"] = " ".join(
            x for x in (details.get("client_addr"), f"({details['client_hostname']})") if x)
    for key, _ in TIME_LABELS:                    # every time but the evidence time, which the table places
        if key != "captured_at" and details.get(key):
            details[key] = fmt_clock(details[key])
    if details.get("reference_as_of"):
        details["reference"] = (t["reference_source"].get(details.get("reference_source"), "") + " · "
                                + datetime.fromisoformat(details["reference_as_of"]).strftime(t["date_format"]))
    for key in DATE_VALUES & details.keys():
        details[key] = template_value_text(key, details[key], t)
    values = {k: template_value_text(k, v, t) for k, v in (f.get("template_values") or {}).items()
              if not k.startswith("_")}
    fields = {**values, **details}
    if f["observed_value"] is not None:
        fields["observed"] = fmt_observed(f["observed_value"], f["observed_unit"], t)
    return fields


def index_cell(name, definition):
    """'ks_child_a' over 'btree (a)' from pg_get_indexdef."""
    short = re.sub(r"^CREATE (UNIQUE )?INDEX \S+ ON \S+ USING ", "", definition or "")
    return e(name) + (f"<br><code>{e(short)}</code>" if short else "")


# Columns per rule (option B, Hasan 2026-11-10): (field, label key in TEXTS). Rules not listed here
# show the finding sentence with the details that are present.
SESSION_COLUMNS = [("pid", "col_pid"), ("observed", "col_duration"), ("database", "detail_database"),
                   ("user", "detail_user"), ("application", "detail_application"),
                   ("client_addr", "detail_client")]
SETTING_COLUMNS = [("node", "detail_node"), ("setting", "detail_setting"), ("value", "detail_value"),
                   ("setting_source", "detail_setting_source")]
FINDING_COLUMNS = {
    "PG-TRAN-001": SESSION_COLUMNS + [("last_query", "detail_last_query")],
    "PG-TRAN-003": SESSION_COLUMNS + [("state", "detail_state"), ("last_query", "detail_last_query")],
    "PG-TRAN-007": SESSION_COLUMNS + [("wait_event", "detail_wait_event"), ("last_query", "detail_last_query")],
    "PG-TRAN-002": [("database_name", "detail_database"), ("observed", "col_xid_age")],
    "PG-TRAN-004": [("database_name", "detail_database"), ("observed", "col_mxid_age")],
    "PG-TRAN-006": [("database_name", "detail_database"), ("xid_age", "col_xid_age"),
                    ("freeze_max_age", "col_freeze_max_age"), ("observed", "col_share")],
    "PG-MAINT-001": [("database", "detail_database"), ("table", "detail_table"), ("live_rows", "detail_live_rows"),
                     ("dead_rows", "detail_dead_rows"), ("observed", "col_share")],
    "PG-MAINT-002": [("database", "detail_database"), ("table", "detail_table"), ("live_rows", "detail_live_rows"),
                     ("modified_rows", "detail_modified_rows"), ("observed", "col_share"),
                     ("analyze_status", "detail_analyze_status")],
    "PG-MAINT-003": [("database", "detail_database"), ("table", "detail_table"), ("live_rows", "detail_live_rows"),
                     ("modified_rows", "detail_modified_rows"), ("analyze_trigger", "detail_analyze_trigger")],
    "PG-IDX-001": [("database", "detail_database"), ("table", "detail_table"), ("index", "detail_index"),
                   ("index_size", "detail_index_size"), ("nodes_checked", "detail_nodes_checked")],
    "PG-IDX-002": [("database", "detail_database"), ("table", "detail_table"), ("index", "detail_index"),
                   ("index_size", "detail_index_size")],
    "PG-IDX-003": [("database", "detail_database"), ("table", "detail_table"), ("index_def", "detail_index"),
                   ("match", "col_match"), ("other_def", "col_other_index"), ("index_size", "detail_index_size")],
    "PG-IDX-004": [("database", "detail_database"), ("table", "detail_table"), ("constraint", "col_foreign_key"),
                   ("columns", "col_columns"), ("referenced", "col_referenced"), ("observed", "col_table_size")],
    "PG-BKP-003": [("database", "detail_database"), ("table", "detail_table"), ("observed", "col_table_size")],
    "PG-CAP-002": [("sequence", "detail_sequence"), ("column", "detail_column"), ("observed", "col_usage"),
                   ("last_value", "detail_last_value"), ("limit", "detail_limit"),
                   ("limit_source", "detail_limit_source")],
    "PG-SEC-001": [("role", "detail_role"), ("valid_until", "detail_valid_until")],
    "PG-SEC-004": [("database", "detail_database"), ("schema", "detail_schema"),
                   ("schema_owner", "detail_schema_owner")],
    "PG-HA-002": [("node_name", "detail_node"), ("started_at", "detail_started_at"), ("observed", "col_since")],
    "PG-LIFE-001": [("node_name", "detail_node"), ("version", "col_version"), ("latest", "col_latest"),
                    ("observed", "col_behind"), ("reference", "col_reference")],
    "PG-LIFE-002": [("node_name", "detail_node"), ("version", "col_version"),
                    ("end_of_support", "col_end_of_support"), ("days_left", "col_days_left")],
    "PG-LIFE-004": [("database_name", "detail_database"), ("extension", "col_extension"),
                    ("installed", "col_installed"), ("available", "col_available")],
    **{key: SETTING_COLUMNS for key in ("PG-CONF-001", "PG-CONF-002", "PG-CONF-004", "PG-CONF-005",
                                        "PG-SEC-002", "PG-SEC-003", "PG-BKP-002")},
}
CODE_FIELDS = {"last_query"}
RIGHT_FIELDS = {"observed", "live_rows", "dead_rows", "modified_rows", "analyze_trigger", "index_size",
                "last_value", "limit", "xid_age", "freeze_max_age", "pid"}
# Settings whose value is empty say so; an empty cell elsewhere means nothing was observed.
EMPTY_SHOWN = {"value"}


def generic_columns(fields_list):
    """Sentence, measured value, then the details present in any finding (option A)."""
    columns = [("sentence", "col_finding")]
    if any("observed" in f for f in fields_list):
        columns.append(("observed", "observed"))
    columns += [(key, label) for key, label in DETAIL_LABELS
                if key not in ("definition", "other_definition") and any(f.get(key) for f in fields_list)]
    columns += [(key, label) for key, label in TIME_LABELS
                if key != "captured_at" and any(f.get(key) for f in fields_list)]
    if any(f.get("last_query") for f in fields_list):
        columns.append(("last_query", "detail_last_query"))
    return columns


def cell(key, fields):
    if key == "index_def":
        return index_cell(fields.get("index"), fields.get("definition"))
    if key == "other_def":
        return index_cell(fields.get("other_index"), fields.get("other_definition"))
    value = fields.get(key)
    if value == "" and key in EMPTY_SHOWN:
        return f'<span class="note">{e(fields.get("_empty") or "")}</span>'
    if value in (None, ""):
        return ""
    return f"<code>{e(value)}</code>" if key in CODE_FIELDS else e(value)


def findings_table(result, findings, data, lang, t):
    """The findings of one rule as one table; the evidence time below it when it is the same for all."""
    fields_list = []
    for f in findings:
        fields = finding_fields(f, t)
        fields["sentence"] = finding_sentence(f, data, lang)
        fields["_severity"] = f["severity"]
        fields["_empty"] = t["empty_value"]
        fields_list.append(fields)
    # Findings stored before their rule had structured values (or by hand) keep the sentence.
    structured = all(f.get("details") and f.get("template_values") for f in findings)
    columns = (FINDING_COLUMNS.get(result["rule_key"]) if structured else None) or generic_columns(fields_list)
    # A column nobody has a value for (query texts of offline evidence, say) is left out.
    columns = [(key, label) for key, label in columns
               if key in ("index_def", "other_def") or key in EMPTY_SHOWN
               or any(fl.get(key) not in (None, "") for fl in fields_list)]
    # Seconds apart within one check are one moment for the reader (lab hc114, 2026-11-11).
    stamps = sorted(x for x in (f.get("captured_at") for f in fields_list) if x)
    parsed = [datetime.fromisoformat(x) for x in stamps]
    same_time = not parsed or (parsed[-1] - parsed[0]).total_seconds() < 60
    times = {stamps[0]} if stamps else {None}
    if not same_time:
        columns = columns + [("captured_at", "detail_captured_at")]
    head = (f'<th>{e(t["col_severity"])}</th>'
            + "".join(f'<th class="num">{e(t[label])}</th>' if key in RIGHT_FIELDS
                      else f"<th>{e(t[label])}</th>" for key, label in columns))

    def rows(items):
        out = []
        for fields in items:
            severity = fields["_severity"]
            cells = "".join(
                f'<td class="num">{cell(key, fields)}</td>' if key in RIGHT_FIELDS
                else f"<td>{e(fmt_clock(fields[key])) if key == 'captured_at' and fields.get(key) else cell(key, fields)}</td>"
                for key, _ in columns)
            out.append(f"<tr><td>{badge(severity, t['severity'].get(severity, severity))}</td>{cells}</tr>")
        return "".join(out)

    shown, rest = fields_list[:FINDINGS_SHOWN], fields_list[FINDINGS_SHOWN:]
    table = lambda items: f'<table class="ftable"><thead><tr>{head}</tr></thead><tbody>{rows(items)}</tbody></table>'
    html_out = table(shown)
    if rest:
        html_out += (f'<details class="more"><summary>{e(t["show_all"].format(n=len(fields_list)))}</summary>'
                     + table(rest) + "</details>")
    if same_time and next(iter(times)):
        html_out += f'<div class="facts">{e(t["detail_captured_at"])}: {e(fmt_clock(next(iter(times))))}</div>'
    return html_out


def parameter_line(result, t):
    params = result.get("parameters") or {}
    if not params:
        return ""
    return f"{t['parameters']}: " + " · ".join(
        f"{key} = {fmt_quantity(p['value'], p['unit'], t)}" for key, p in sorted(params.items()))


def unassessed_line(result, t):
    """'Server not assessed: postgre-2 (data not collected)' for a result with partial coverage."""
    items = [f'{u["node"]} ({t["unassessed_reason"].get(u["reason_code"], u["reason_code"])})'
             for u in result.get("unassessed") or []]
    return t["unassessed_line"].format(items=", ".join(items)) if items else ""


def hardware_missing_nodes(data):
    """Nodes whose memory or data disk is unknown, when other nodes' are known (partial host data)."""
    nodes = [n for n in data["nodes"] if n.get("data_directory")]     # the nodes the engine used
    missing = [n["name"] for n in nodes
               if not n.get("memory_total_bytes") or data_disk(n, data["storage"]) is None]
    return missing if 0 < len(missing) < len(nodes) else []


def render_findings_detail(data, lang, t):
    cards = []
    for result, findings in findings_by_rule(data):
        if result["rule_key"] == CONFIG_RULE and data.get("config"):
            continue                         # shown as the configuration table instead
        # Worst first, then the largest measured value.
        findings = sorted(findings, key=lambda f: (SEVERITY_ORDER.get(f["severity"], 9),
                                                   -float(f["observed_value"] or 0)))
        worst = findings[0]["severity"]
        rid = result["rule_id"]
        facts = [x for x in (threshold_line(result, t), parameter_line(result, t),
                             unassessed_line(result, t)) if x]
        cards.append(
            f'<details class="card {e(worst)}"><summary><h3>{badge(worst, t["severity"].get(worst, worst))}'
            f'{e(rule_text(data, rid, lang, "NAME", result["rule_name"]))}'
            f'<span class="note">{len(findings)} {e(t["findings_word"])}</span>'
            f'<span class="rule">{e(result["rule_key"])}</span></h3></summary>'
            + "".join(f'<div class="facts">{e(x)}</div>' for x in facts)
            + "<dl>"
            + problem_rows(data, rid, lang, t, findings, short=False)
            + "</dl>" + findings_table(result, findings, data, lang, t) + "</details>")
    return f"<h2>{e(t['findings'])}</h2>" + (
        "".join(cards) or f'<p class="note">{e(t["no_findings"])}</p>')


def render_results(data, lang, t):
    rows = []
    for key, topic in topic_summary(data):
        entry = data["topics"].get(key)
        topic_name = localized(entry, lang, "name") if entry else ""
        for r in topic["results"]:
            name = rule_text(data, r["rule_id"], lang, "NAME", r["rule_name"])
            if r["outcome"] == "HEALTHY":
                note = healthy_text(data, r, lang, t)
            elif r["outcome"] == "ATTENTION_REQUIRED":
                count = sum(1 for f in data["findings"] if f["rule_id"] == r["rule_id"])
                note = " · ".join(x for x in (f"{count} {t['findings_word']}", threshold_line(r, t),
                                              unassessed_line(r, t)) if x)
            else:
                note = explain_reason(r["reason"], data, t)
            # A rule with findings shows their severity, the word used everywhere else in the report.
            if r["outcome"] == "ATTENTION_REQUIRED" and r["max_severity"]:
                status = badge(r["max_severity"], t["severity"].get(r["max_severity"], r["max_severity"]))
            else:
                status = badge(r["outcome"], t["outcome"].get(r["outcome"], r["outcome"]))
            rows.append([e(topic_name), f'{e(name)} <span class="rule">{e(r["rule_key"])}</span>',
                         status, e(note)])
    return f"<h2>{e(t['results'])}</h2>" + table(
        [t["area"], t["rule"], t["status"], ""], rows)


def render_collections(data, t):
    purpose = {"EVIDENCE": t["purpose_evidence"], "CONTEXT": t["purpose_context"]}
    ok = sum(1 for c in data["collections"] if c["status"] in ("SUCCESS", "PARTIAL_SUCCESS"))
    summary = t["collected_count"].format(ok=ok, total=len(data["collections"]))
    return (f'<details class="section"><summary><h2>{e(t["collection"])}'
            f'<span class="note">{e(summary)}</span></h2></summary>' + table(
        [t["collector"], t["node"], t["purpose"], t["status"]],
        [[e(c["collector_key"]), e(c["target_name"]), e(purpose.get(c["purpose"], c["purpose"])),
          badge(c["status"], t["collection_status"].get(c["status"], c["status"])) + (
              f'<div class="facts">{e(c["status_message"])}</div>' if c["status_message"] else "")]
         for c in data["collections"]]) + "</details>")


# ---------------------------------------------------------------- configuration (ADR-0017)

HOST_REASONS = ("no_memory", "no_cpus", "no_disk")
CONFIG_RULE = "PG-CONF-003"


def config_counts(data):
    counts = {"FITS": 0, "DEVIATES": 0, "NOT_ASSESSED": 0, "NOT_APPLICABLE": 0}
    for r in data.get("config") or []:
        counts[r["status"]] += 1
    return counts


def config_summary(counts, t, statuses=("DEVIATES", "NOT_ASSESSED", "FITS", "NOT_APPLICABLE")):
    """'11 settings differ · 3 fit · 4 not applicable'; statuses with no setting are left out."""
    return " · ".join(t["config_parts"][s].format(n=counts[s]) for s in statuses if counts[s])


def config_number(text):
    if text is None:
        return None
    try:
        return float(text)
    except ValueError:
        return text


def config_value(text, value_type, t):
    """A stored value as the report shows it: PostgreSQL syntax, 'off' for -1."""
    value = config_number(text)
    if value is None:
        return ""
    if not isinstance(value, str) and value < 0:
        return t["config_off"]
    if not isinstance(value, str):
        value = config_rec.round_for(value, value_type)
    return config_rec.pg_value(value, value_type)


def calc_text(row, t, profile):
    """The calculation in one line, from the stored values: '1945MB × ½ × %25 = 486MB'."""
    c = row.get("calculation") or {}
    vt = row["value_type"]
    pg = lambda v: config_rec.pg_value(config_rec.round_for(float(v), "BYTE"), "BYTE")   # noqa: E731
    result = config_value(row["recommended_value"], vt, t)
    method = c.get("method")
    half = " × ½" if c.get("dedicated_share", 1) == 0.5 else (
        f" × {c['dedicated_share']:g}" if c.get("dedicated_share", 1) != 1 else "")
    rec = config_number(row["recommended_value"])
    # When a lower or upper limit decided the value, the product is shown first, then the limit:
    # '36 CPU × 0.5 = 18 → upper limit 4 = 4' (Hasan 2026-11-11: '36 × 0.5 = 4' read as wrong).
    bound = None
    if c.get("min") is not None and rec == c["min"]:
        bound = (t["config_calc_lower"], c["min"])
    elif c.get("max") is not None and rec == c["max"]:
        bound = (t["config_calc_upper"], c["max"])

    def ends(raw, show):
        if bound is None or raw is None or abs(raw - rec) < 1:
            return f" = {result}"
        return f" = {show(raw)} → {bound[0]} {config_value(str(bound[1]), vt, t)} = {result}"

    if method == "memory_share":
        share = t["percent"].format(n=f"{c['share'] * 100:g}")
        raw = c["memory"] * c.get("dedicated_share", 1) * c["share"]
        return f"{pg(c['memory'])}{half} × {share}" + ends(raw, pg)
    if method == "work_mem":
        raw = ((c["memory"] * c.get("dedicated_share", 1) - c["shared_buffers"])
               / (c["max_connections"] * c["factor"]))
        return (f"({pg(c['memory'])}{half} − shared_buffers {pg(c['shared_buffers'])}) / "
                f"({c['max_connections']:g} {t['config_connections']} × {c['factor']:g})" + ends(raw, pg))
    if method == "max_wal_size":
        workload = t["profile_values"].get(profile.get("workload_type", {}).get("value"), "")
        text = f"{t['profile_workload_type']} {workload}: {pg(c['value'])}"
        if c.get("capped"):
            cap = t["config_calc_cap"].format(share=f"{c['disk_share'] * 100:g}")
            text += f"; {cap} ({pg(c['disk'])}) = {result}"
        return text
    if method == "checkpoint_evidence":
        text = t["config_calc_checkpoints"].format(
            total=c["total"], requested=c["requested"], share=f"{c['share'] * 100:.0f}",
            current=pg(c["current"]), factor=f"{c['factor']:g}", result=result)
        if c.get("capped"):
            cap = t["config_calc_cap"].format(share=f"{c['disk_share'] * 100:g}")
            text += f"; {cap} ({pg(c['disk'])})"
        return text
    if method == "share_of":
        return f"{c['of']} {pg(c['base'])} × {c['share']:g} = {result}"
    if method == "cpu_share":
        raw = math.ceil(c["cpus"] * c["share"])
        return f"{t['config_cpus'].format(n=c['cpus'])} × {c['share']:g}" + ends(raw, lambda v: f"{v:g}")
    return ""


def config_inputs(data, t):
    """'Calculated for the smallest server: node (1 CPU, 1.9 GB, data disk 11.2 GB).'"""
    nodes = [n for n in data["nodes"] if n.get("memory_total_bytes")]
    if not nodes or hardware_missing_nodes(data):
        return ""                          # no smallest server when one node is unknown
    smallest = min(nodes, key=lambda n: n["memory_total_bytes"])
    facts = [t["config_cpus"].format(n=min(n["logical_cpu_count"] for n in nodes if n.get("logical_cpu_count")))
             if any(n.get("logical_cpu_count") for n in nodes) else "",
             fmt_bytes(smallest["memory_total_bytes"])]
    disks = [d for n in data["nodes"] if (d := data_disk(n, data["storage"]))]
    if disks:
        facts.append(t["config_disk"].format(v=fmt_bytes(min(d["total_bytes"] for d in disks))))
    return t["config_inputs"].format(node=smallest["name"], facts=", ".join(f for f in facts if f))


# systemd-detect-virt codes as people know them ("oracle" is VirtualBox, not the database).
HYPERVISOR_NAMES = {
    "oracle": "VirtualBox", "vmware": "VMware", "kvm": "KVM", "qemu": "QEMU", "microsoft": "Hyper-V",
    "xen": "Xen", "amazon": "AWS Nitro", "google": "Google Compute Engine", "parallels": "Parallels",
    "bhyve": "bhyve", "zvm": "z/VM", "powervm": "PowerVM", "apple": "Apple Virtualization",
}


def config_disk_note(data, t, profile):
    """A note when the data disk reports another type than the profile (lsblk ROTA); '' otherwise.

    Note only: virtual disks often report rotating on SSD, so the profile stays the input.
    """
    entry = profile.get("storage_type")
    if not entry:
        return ""
    differing = []
    for n in data["nodes"]:
        disk = data_disk(n, data["storage"])
        if disk is None or disk.get("rotational") is None:
            continue
        observed = "HDD" if disk["rotational"] else "SSD"
        if observed != entry["value"]:
            differing.append((n, observed))
    if not differing:
        return ""
    observed = differing[0][1]                      # the profile has one value, so the other one
    values = t["profile_values"]
    text = t["config_disk_assumed" if entry.get("assumed") else "config_disk_conflict"].format(
        profile=values.get(entry["value"], entry["value"]), observed=values.get(observed, observed),
        nodes=", ".join(n["name"] for n, _ in differing))
    virtual = sorted({HYPERVISOR_NAMES.get(n["virtualization"], n["virtualization"]) for n, o in differing
                      if o == "HDD" and n.get("virtualization") not in (None, "none")})
    if virtual:
        text += " " + t["config_disk_virtual"].format(virt=", ".join(virtual))
    return text


def config_why(row, data, lang, t, profile):
    reasons = data["config_reasons"].get(row["setting_key"], {})
    parts = [reasons.get(lang) or reasons.get(FALLBACK_LANGUAGE, "")]
    if row["status"] in ("NOT_ASSESSED", "NOT_APPLICABLE"):
        return e(t["config_reason"].get(row["reason_code"], row["reason_code"] or ""))
    calc = calc_text(row, t, profile)
    html_ = e(parts[0])
    if calc:
        html_ += f'<div class="facts">{e(calc)}</div>'
    for field in row.get("assumptions") or []:
        value = t["profile_values"].get(profile.get(field, {}).get("value"), "")
        html_ += f'<div class="facts"><i>{e(t["config_assumed"].format(field=t["config_fields"][field], value=value))}</i></div>'
    for d in row.get("node_differences") or []:
        html_ += f'<div class="facts">{e(t["config_differs"].format(node=d["node"], value=d["value"]))}</div>'
    return html_


def config_row(row, data, lang, t, profile):
    vt = row["value_type"]
    name = e(row["setting_key"]) + (" ↻" if row.get("restart_required") else "")
    acceptable = config_rec.acceptable_text(row["acceptable"], vt) if row.get("acceptable") else ""
    return [name, e(config_value(row["current_value"], vt, t)),
            e(config_value(row["recommended_value"], vt, t)) if row["recommended_value"] else "—",
            e(acceptable) or "—", config_why(row, data, lang, t, profile)]


def command_blocks(rows, profile, t, cluster=None, patroni_possible=True):
    """[(title, text)] of commands for the settings to change (review 2026-11-09).

    Reload and restart apart; ALTER SYSTEM or patronictl by the profile's cluster_manager, both
    commented out when it is not given; a value resting on an assumed profile field is a comment.
    """
    manager = (profile.get("cluster_manager") or {}).get("value")
    changes = []
    for r in rows:
        if r["status"] != "DEVIATES" or not r["recommended_value"]:
            continue
        value = config_value(r["recommended_value"], r["value_type"], t)
        assumed = [t["config_assumed"].format(field=t["config_fields"].get(f, f),
                                              value=t["profile_values"].get(profile.get(f, {}).get("value"),
                                                                            profile.get(f, {}).get("value")))
                   for f in r.get("assumptions") or []]
        note = t["config_assumed_cmd"].format(items="; ".join(assumed)) if assumed else ""
        changes.append((r["setting_key"], value, bool(r.get("restart_required")), note))
    if not changes:
        return []
    sure = manager is not None

    def sql_line(k, v, note):
        line = f"ALTER SYSTEM SET {k} = '{v}';"
        return f"-- {line}  -- {note}" if note else (line if sure else f"-- {line}")

    blocks = []
    if manager in (None, "NONE"):
        reload = [sql_line(k, v, n) for k, v, restart, n in changes if not restart]
        if reload:
            tail = "SELECT pg_reload_conf();"
            blocks.append((t["config_block_reload"], "\n".join(reload + [tail if sure else f"-- {tail}"])))
        restart = [sql_line(k, v, n) for k, v, restart, n in changes if restart]
        if restart:
            blocks.append((t["config_block_restart"], "\n".join(restart + [f"-- {t['config_restart_hint']}"])))
    if manager == "PATRONI" or (manager is None and patroni_possible):
        # patronictl restart needs the cluster name (Patroni 4.1, lab 2026-11-09); Patroni sets cluster_name.
        name = f" {cluster or '<cluster>'}"
        direct = [(k, v) for k, v, _, n in changes if not n]
        lines = []
        if direct:
            lines.append(f"patronictl edit-config{name} \\\n"
                         + " \\\n".join(f"  --pg {k}={v}" for k, v in direct))
        lines += [f"# patronictl edit-config{name} --pg {k}={v}  # {n}" for k, v, _, n in changes if n]
        text = "\n".join(lines)
        if not sure:
            text = "\n".join(line if line.startswith("#") else f"# {line}" for line in text.split("\n"))
        blocks.append((t["config_block_patroni"], text))
        if any(restart and not n for _, _, restart, n in changes):
            command = f"patronictl restart{name} --pending"
            blocks.append((t["config_block_patroni_restart"], command if sure else f"# {command}"))
    return blocks


def config_commands(data, rows, t):
    profile = data["check"].get("target_profile") or {}
    # Windows without a sign of Patroni: patronictl lines would only confuse (pilot hc111, 2026-11-11).
    windows = any("windows" in (n.get("os_name") or "").lower() for n in data["nodes"])
    patroni_possible = not windows or bool(data.get("patroni_seen"))
    blocks = command_blocks(rows, profile, t, data.get("cluster_name"), patroni_possible=patroni_possible)
    if not blocks:
        return ""
    parts = [f"<h3>{e(t['config_commands'])}</h3><p class=\"note\">{e(t['config_commands_note'])}</p>"]
    if (profile.get("cluster_manager") or {}).get("value") is None:
        hint = f" {t['config_patroni_seen']}" if data.get("patroni_seen") else ""
        note = t["config_block_unknown"] if patroni_possible else t["config_block_unknown_plain"]
        parts.append(f'<p class="note">{e(note + hint)}</p>')
    for title, text in blocks:
        parts.append(f'<div class="facts">{e(title)}:</div><div class="cmd">{e(text)}</div>')
    if any("patronictl" in text for _, text in blocks):
        parts.append(f'<p class="note">{e(t["config_patroni_config"])}</p>')
    return "".join(parts)


# From this many connections work_mem is divided so thin that the connections are the lever (pooler).
MANY_CONNECTIONS = 500


def render_config(data, lang, t):
    rows = data.get("config") or []
    if not rows:
        return ""
    profile = data["check"].get("target_profile") or {}
    counts = config_counts(data)
    action = [r for r in rows if r["status"] == "DEVIATES"]
    missing = [r for r in rows if r["status"] == "NOT_ASSESSED"]
    fine = [r for r in rows if r["status"] in ("FITS", "NOT_APPLICABLE")]
    summary = config_summary(counts, t)
    inputs = config_inputs(data, t)
    parts = [f'<details class="section"><summary><h2>{e(t["config_title"])}'
             f'<span class="note">{e(summary)}</span></h2></summary>']
    parts.append(f'<p class="note">{e(inputs)}</p>' if inputs else "")
    disk_note = config_disk_note(data, t, profile)
    parts.append(f'<p class="note">{e(disk_note)}</p>' if disk_note else "")
    # Review 2026-11-11: a recommendation is no more certain than its inputs. Without a profile the
    # values are a starting point; with very many connections the lever is the connections.
    if any(r.get("assumptions") for r in action):
        parts.append(f'<p class="note"><b>{e(t["config_starting_values"])}</b></p>')
    connections = next((r["calculation"].get("max_connections") for r in rows
                        if r["setting_key"] == "work_mem" and (r.get("calculation") or {}).get("max_connections")),
                       None)
    if connections and connections >= MANY_CONNECTIONS:
        parts.append(f'<p class="note">{e(t["config_many_connections"].format(n=f"{connections:g}"))}</p>')
    if action:
        parts.append(table(t["config_cols"], [config_row(r, data, lang, t, profile) for r in action]))
        if any(r.get("restart_required") for r in action):
            parts.append(f'<p class="note">{e(t["config_restart"])}</p>')
    # Settings without a recommendation: one line per cause, not a table row each.
    by_reason = {}
    for r in missing:
        code = "no_host" if r["reason_code"] in HOST_REASONS else r["reason_code"]
        by_reason.setdefault(code, []).append(r["setting_key"])
    partial_hosts = hardware_missing_nodes(data)
    for code, names in by_reason.items():
        cause = t["config_reason"].get(code, code or "")
        if code == "no_host" and partial_hosts:
            cause = t["config_host_partial"].format(nodes=", ".join(partial_hosts))
        parts.append(f'<p><b>{e(t["config_not_assessed"].format(n=len(names)))}</b>: '
                     f'{e(", ".join(names))}<span class="facts"> — {e(cause)}</span></p>')
    parts.append(config_commands(data, rows, t))
    if fine:
        parts.append(f'<details class="more"><summary>{e(config_summary(counts, t, ("FITS", "NOT_APPLICABLE")))}</summary>'
                     + table(t["config_cols"], [config_row(r, data, lang, t, profile) for r in fine])
                     + "</details>")
    return "".join(parts) + "</details>"


def render_technical(data, lang, t):
    offline = data["check"].get("source") == "OFFLINE"
    return (f'<div class="part part-tech">{e(t["part_tech"])}</div>'
            + render_system(data, t) + render_findings_detail(data, lang, t)
            + render_config(data, lang, t) + render_results(data, lang, t) + render_collections(data, t)
            + f"<h2>{e(t['method'])}</h2><p>{e(t['method_text_offline' if offline else 'method_text'])}</p>")


def render_html(data, lang="tr"):
    t = TEXTS[lang]
    # CSS-only tabs (no script): works in mail clients and locked-down browsers; print shows both.
    tabs = ('<div class="tabs">'
            f'<input type="radio" name="part" id="tab-exec" checked><label for="tab-exec">{e(t["part_exec"])}</label>'
            f'<input type="radio" name="part" id="tab-tech"><label for="tab-tech">{e(t["part_tech"])}</label>'
            f'<div class="panel panel-exec">{render_executive(data, lang, t)}</div>'
            f'<div class="panel panel-tech">{render_technical(data, lang, t)}</div></div>')
    body = (render_header(data, t) + tabs
            + f"<footer>{e(t['generated'])}: {e(fmt_time(datetime.now(timezone.utc).astimezone()))}"
            " · Keystone</footer>")
    return (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(t['title'])} - {e(data['check']['target_name'])}</title><style>{STYLE}</style>"
            f"</head><body><main>{body}</main></body></html>")


def default_file_name(data, lang):
    """<target>_<check start yyyymmdd-hhmm>_hc<id>_<lang>.html; sorts by time in a folder."""
    check = data["check"]
    target = re.sub(r"[^A-Za-z0-9_-]+", "-", check["target_name"]).strip("-") or "target"
    stamp = check["started_at"].strftime("%Y%m%d-%H%M")
    return f"{target}_{stamp}_hc{check['health_check_id']}_{lang}.html"


def write_report(conn, health_check_id, lang="tr", output=None):
    """Render and write the report; returns the file path."""
    if lang not in TEXTS:
        raise ValueError(f"Unsupported report language: {lang} (available: {', '.join(TEXTS)})")
    data = load_report_data(conn, health_check_id)
    path = Path(output) if output else Path(DEFAULT_OUTPUT_DIR) / default_file_name(data, lang)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(data, lang), encoding="utf-8")
    # Say which check: this command reports an existing check, it does not collect.
    logger.info("Report of health check %s (%s, started %s) written: %s",
                health_check_id, data["check"]["target_name"],
                fmt_time(data["check"]["started_at"]), path)
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m repository.report.health_check_report",
        description="Write the HTML report of an existing health check (does not collect; "
                    "run repository.healthcheck.health_check for a new check).",
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--health-check", type=int, help="health_check_id")
    which.add_argument("--target", type=int, help="latest completed health check of this target")
    parser.add_argument("--lang", default="tr", choices=sorted(TEXTS), help="report language (default: tr)")
    parser.add_argument("--output", help=f"file path (default: {DEFAULT_OUTPUT_DIR}/<target>_<yyyymmdd-hhmm>_hc<id>_<lang>.html)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging("report", connect=worker.connect_repository)
    with worker.connect_repository() as conn:
        check_id = args.health_check or latest_health_check_id(conn, args.target)
        write_report(conn, check_id, args.lang, args.output)


if __name__ == "__main__":
    main()
