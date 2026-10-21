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
from datetime import datetime, timezone
import html
from pathlib import Path
import re

from repository.common.logging_config import configure_logging, get_logger
from repository.intelligence.assessment_engine import data_mount, usage_percent
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
        "part_exec": "Yönetici Özeti", "part_tech": "Teknik Detaylar",
        "verdict_critical": "Acil müdahale gerektiren sorunlar var.",
        "verdict_warning": "Dikkat gerektiren sorunlar var.",
        "verdict_healthy": "Değerlendirilen alanlarda sorun bulunmadı.",
        "verdict_none": "Hiçbir kontrol değerlendirilemedi; veri toplanamadı.",
        "coverage": "{total} kontrol yapıldı, {evaluated} tanesi sonuç verdi.",
        "not_assessed_note": "{count} kontrol yeterli veri olmadığı için değerlendirilemedi.",
        "count_critical": "Kritik", "count_warning": "Uyarı",
        "count_healthy": "Sağlıklı", "count_not_assessed": "Değerlendirilemedi",
        "inventory_title": "Sistem envanteri",
        "inv_servers": "Sunucu", "inv_version": "PostgreSQL", "inv_cpu": "CPU", "inv_memory": "Bellek",
        "inv_data": "Veri", "inv_disk": "Disk",
        "inv_roles": "{primary} primary, {replica} replica", "inv_cores": "{n} çekirdek",
        "inv_databases": "{n} veritabanı", "inv_partial": "{known} / {total} sunucu için",
        "inv_unknown": "Toplanamadı", "percent": "%{n}", "inv_full": "{p} dolu",
        "inv_data_disk": "Veri diski", "inv_role": "Rol", "inv_disk_unknown": "Bilinmiyor",
        "inv_large_note": "Sunucu bazlı ayrıntı Teknik Detaylar bölümünde.",
        "data_mount": "veri",
        "impact_title": "Etkilenen alanlar",
        "impact_none": "Sorun bulunmadı", "impact_not_checked": "Bu kontrolde incelenmedi",
        "findings_word": "bulgu",
        "topics_title": "Alanlara göre durum",
        "topic_ok": "Sorun bulunmadı", "topic_attention": "Dikkat", "topic_critical": "Kritik",
        "topic_unknown": "Değerlendirilemedi",
        "topic_unknown_text": "Yeterli veri toplanamadığı için değerlendirilemedi.",
        "problems_title": "Öne çıkan sorunlar", "no_problems": "Öne çıkan bir sorun yok.",
        "why_it_matters": "Neden önemli", "what_to_do": "Ne yapılmalı", "what_happens": "Ne oluyor", "causes": "Olası sebepler",
        "system": "Sistem Bilgisi",
        "nodes": "Sunucular", "node": "Sunucu", "address": "Adres", "role": "Rol",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Çalışma süresi", "os": "İşletim sistemi", "cpu": "CPU", "memory": "Bellek",
        "storage": "Disk kullanımı", "mount": "Bağlama noktası", "used": "Kullanılan",
        "total": "Toplam",
        "databases": "Veritabanları", "database": "Veritabanı", "owner": "Sahip", "size": "Boyut",
        "not_collected_here": "Bu kontrolde toplanamadı.",
        "collection_summary": "Veri toplama: {ok} / {total} başarılı",
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
        "detail_apply_delay": "Bilinçli uygulama gecikmesi", "detail_beyond_delay": "Bilinçli gecikmenin üzerindeki kısım",
        "detail_slot": "Slot", "detail_slot_type": "Slot tipi", "detail_wal_status": "WAL durumu",
        "detail_sync_names": "synchronous_standby_names",
        "billion": "milyar", "unit_TRANSACTION": "transaction", "unit_CONNECTION": "bağlantı",
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
        "generated": "Rapor oluşturma zamanı",
        "outcome": {"HEALTHY": "Sağlıklı", "ATTENTION_REQUIRED": "Dikkat",
                    "INSUFFICIENT_EVIDENCE": "Veri yetersiz", "ERROR": "Hata"},
        "severity": {"CRITICAL": "Kritik", "WARNING": "Uyarı", "INFO": "Bilgi"},
        "collection_status": {"SUCCESS": "Başarılı", "PARTIAL_SUCCESS": "Kısmen başarılı",
                              "FAILED": "Başarısız", "CONNECTION_FAILED": "Bağlantı hatası",
                              "TIMEOUT": "Zaman aşımı", "STALE": "Yarıda kaldı",
                              "NOT_COLLECTED": "Toplanamadı", "WAIT_LIMIT": "Beklenmedi"},
        "days": "gün", "hours": "saat", "minutes": "dakika",
        "reason_not_collected": "{source} bu kontrolde toplanamadı ({status}: {message}).",
        "reason_stale": "{source} verisi {age} önce toplanmış; bu kontrol için en fazla {limit} eski veri kabul ediliyor.",
        "reason_missing": "{source} verisi yok.",
    },
    "en": {
        "title": "Database Health Check Report",
        "target": "System", "date": "Date", "check_no": "Check no", "requested_by": "Requested by",
        "part_exec": "Executive Summary", "part_tech": "Technical Details",
        "verdict_critical": "There are problems that need immediate action.",
        "verdict_warning": "There are problems that need attention.",
        "verdict_healthy": "No problems were found in the assessed areas.",
        "verdict_none": "No check could be evaluated; data could not be collected.",
        "coverage": "{total} checks were run, {evaluated} produced a result.",
        "not_assessed_note": "{count} check(s) could not be evaluated for lack of data.",
        "count_critical": "Critical", "count_warning": "Warning",
        "count_healthy": "Healthy", "count_not_assessed": "Not assessed",
        "inventory_title": "System inventory",
        "inv_servers": "Servers", "inv_version": "PostgreSQL", "inv_cpu": "CPU", "inv_memory": "Memory",
        "inv_data": "Data", "inv_disk": "Disk",
        "inv_roles": "{primary} primary, {replica} replica", "inv_cores": "{n} cores",
        "inv_databases": "{n} databases", "inv_partial": "for {known} of {total} servers",
        "inv_unknown": "Not collected", "percent": "{n}%", "inv_full": "{p} used",
        "inv_data_disk": "Data disk", "inv_role": "Role", "inv_disk_unknown": "Unknown",
        "inv_large_note": "Per-server details are in the Technical Details part.",
        "data_mount": "data",
        "impact_title": "Affected areas",
        "impact_none": "No problems found", "impact_not_checked": "Not covered by this check",
        "findings_word": "finding(s)",
        "topics_title": "Status by area",
        "topic_ok": "No problems found", "topic_attention": "Attention", "topic_critical": "Critical",
        "topic_unknown": "Not assessed",
        "topic_unknown_text": "Could not be assessed; not enough data was collected.",
        "problems_title": "Main problems", "no_problems": "No problems to highlight.",
        "why_it_matters": "Why it matters", "what_to_do": "What to do", "what_happens": "What is happening", "causes": "Likely causes",
        "system": "System Overview",
        "nodes": "Servers", "node": "Server", "address": "Address", "role": "Role",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Uptime", "os": "Operating system", "cpu": "CPU", "memory": "Memory",
        "storage": "Disk usage", "mount": "Mount point", "used": "Used", "total": "Total",
        "databases": "Databases", "database": "Database", "owner": "Owner", "size": "Size",
        "not_collected_here": "Not collected in this check.",
        "collection_summary": "Data collection: {ok} of {total} succeeded",
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
        "detail_apply_delay": "Intended apply delay", "detail_beyond_delay": "Beyond the intended delay",
        "detail_slot": "Slot", "detail_slot_type": "Slot type", "detail_wal_status": "WAL status",
        "detail_sync_names": "synchronous_standby_names",
        "billion": "billion", "unit_TRANSACTION": "transactions", "unit_CONNECTION": "connections",
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
        "generated": "Report generated",
        "outcome": {"HEALTHY": "Healthy", "ATTENTION_REQUIRED": "Attention",
                    "INSUFFICIENT_EVIDENCE": "Insufficient data", "ERROR": "Error"},
        "severity": {"CRITICAL": "Critical", "WARNING": "Warning", "INFO": "Info"},
        "collection_status": {"SUCCESS": "Success", "PARTIAL_SUCCESS": "Partial",
                              "FAILED": "Failed", "CONNECTION_FAILED": "Connection failed",
                              "TIMEOUT": "Timed out", "STALE": "Interrupted",
                              "NOT_COLLECTED": "Not collected", "WAIT_LIMIT": "Not waited for"},
        "days": "days", "hours": "hours", "minutes": "minutes",
        "reason_not_collected": "{source} could not be collected in this check ({status}: {message}).",
        "reason_stale": "{source} data was collected {age} ago; at most {limit} old data is accepted for this check.",
        "reason_missing": "No {source} data.",
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
    as_of = check["finished_at"] or datetime.now(timezone.utc)
    # Context data only from this check: a report is a snapshot of that moment.
    since = check["started_at"]

    results = conn.execute(
        """
        SELECT ad.assessment_key, rd.rule_id, rd.rule_key, rd.name AS rule_name, rd.topic_key,
               res.outcome, res.max_severity, res.reason, ar.assessment_run_id,
               COALESCE(res.thresholds_used, (
                   SELECT jsonb_agg(jsonb_build_object('severity', th.severity,
                                                       'value', th.threshold_value,
                                                       'unit', th.threshold_unit))
                   FROM keystone.rule_threshold th WHERE th.rule_id = rd.rule_id
               )) AS thresholds
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
               f.observed_value, f.observed_unit, f.subject_type, f.subject_identifier, f.details
        FROM keystone.finding f
        JOIN keystone.assessment_run ar ON ar.assessment_run_id = f.assessment_run_id
        WHERE ar.health_check_id = %s
        ORDER BY f.finding_id
        """, (health_check_id,)).fetchall()

    collections = conn.execute(
        "SELECT c.collector_key, c.purpose, c.status, c.status_message, t.name AS target_name "
        "FROM keystone.health_check_collection c JOIN keystone.target t USING (target_id) "
        "WHERE c.health_check_id = %s ORDER BY c.purpose DESC, c.collector_key, t.name",
        (health_check_id,)).fetchall()

    # Servers: the target itself if it is a NODE, else its NODE children.
    nodes = conn.execute(
        """
        SELECT t.target_id, t.name, ii.server_address, ii.server_port, ii.server_version,
               ii.in_recovery, ii.postmaster_start_time,
               hs.hostname, hs.os_name, hs.os_version, hs.logical_cpu_count,
               hs.memory_total_bytes, hs.captured_at AS host_captured_at,
               cs.setting_value AS data_directory
        FROM keystone.target t
        LEFT JOIN postgresql.instance_inventory ii
            ON ii.target_id = t.target_id AND ii.last_collected_at BETWEEN %s AND %s
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
        SELECT t.target_id, t.name AS node_name, s.mount_point, s.used_bytes, s.total_bytes,
               s.available_bytes
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

    dictionary = load_dictionary_texts(conn)
    conn.commit()

    return {"check": check, "results": results, "findings": findings,
            "collections": collections, "nodes": nodes, "storage": storage,
            "databases": databases, "as_of": as_of, **dictionary}


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
    if unit == "PERCENT":
        return t["percent"].format(n=f"{value:g}")
    if unit == "TRANSACTION" and value >= 1e9:
        return f"{value / 1e9:g} {t['billion']} {t['unit_TRANSACTION']}"
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


def explain_reason(reason, data, t):
    """Engine reason in plain words; says when this check failed to collect the source."""
    match = REASON_PATTERN.match(reason or "")
    if not match:
        return reason or ""
    source = match.group("source")
    failed = [c for c in data["collections"] if c["collector_key"] == source
              and c["status"] not in ("SUCCESS", "PARTIAL_SUCCESS")]
    if failed:
        c = failed[0]
        return t["reason_not_collected"].format(
            source=source, status=t["collection_status"].get(c["status"], c["status"]),
            message=c["status_message"] or "-")
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


def summarize(data):
    results = data["results"]
    counts = {"total": len(results), "healthy": 0, "attention": 0, "not_assessed": 0,
              "critical": 0, "warning": 0}
    for r in results:
        if r["outcome"] == "HEALTHY":
            counts["healthy"] += 1
        elif r["outcome"] == "ATTENTION_REQUIRED":
            counts["attention"] += 1
        else:
            counts["not_assessed"] += 1
    # Tiles count checks, so they add up to the total; findings are counted per problem card.
    for r in results:
        if r["outcome"] == "ATTENTION_REQUIRED":
            counts["critical" if r["max_severity"] == "CRITICAL" else "warning"] += 1
    counts["findings"] = len(data["findings"])
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
    summary = {key: {"problems": {}, "checked": False} for key in data["categories"]}
    for rule_id, keys in data["rule_categories"].items():
        for key in keys:
            if rule_id in evaluated and key in summary:
                summary[key]["checked"] = True
    for f in data["findings"]:
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
        outcomes = [r["outcome"] for r in topic["results"]]
        severities = [r["max_severity"] for r in topic["results"] if r["max_severity"]]
        if "CRITICAL" in severities:
            topic["status"] = "critical"
        elif "ATTENTION_REQUIRED" in outcomes:
            topic["status"] = "attention"
        elif "HEALTHY" not in outcomes:
            topic["status"] = "unknown"
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
.topic{display:grid;grid-template-columns:minmax(160px,220px) auto 1fr;gap:6px 14px;align-items:baseline;
padding:9px 0;border-bottom:1px solid var(--line)}
.topic .name{font-weight:600}
table{width:100%;border-collapse:collapse;font-size:14px;margin:6px 0 10px}
th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1px solid var(--line);padding:7px 8px;background:var(--soft)}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}
td.num,th.num{text-align:right;white-space:nowrap}
.badge{display:inline-block;border-radius:4px;padding:1px 8px;font-size:12px;font-weight:600;white-space:nowrap}
.b-CRITICAL,.b-ERROR,.b-critical{background:var(--crit-bg);color:var(--crit)}
.b-WARNING,.b-ATTENTION_REQUIRED,.b-attention{background:var(--warn-bg);color:var(--warn)}
.b-INFO,.b-INSUFFICIENT_EVIDENCE,.b-unknown{background:var(--na-bg);color:var(--na)}
.b-HEALTHY,.b-SUCCESS,.b-ok{background:var(--ok-bg);color:var(--ok)}
.b-FAILED,.b-CONNECTION_FAILED,.b-TIMEOUT,.b-STALE{background:var(--crit-bg);color:var(--crit)}
.b-PARTIAL_SUCCESS,.b-WAIT_LIMIT{background:var(--warn-bg);color:var(--warn)}
.b-NOT_COLLECTED{background:var(--na-bg);color:var(--na)}
.card{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px;margin:10px 0}
.card.CRITICAL{border-left-color:var(--crit)}
.card h3{margin:0 0 6px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.card dl{margin:6px 0 0;display:grid;grid-template-columns:minmax(110px,150px) 1fr;gap:4px 12px}
.card dt{color:var(--muted);font-size:13px;font-weight:600}
.card dd{margin:0}
.items{margin:0;padding-left:18px}.items li{margin:1px 0}
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
table{display:block;overflow-x:auto}.topic{grid-template-columns:1fr auto}.topic .text{grid-column:1/-1}
.impact{grid-template-columns:1fr}.card dl{grid-template-columns:1fr}}
@media print{main{padding:0;max-width:none}h2{break-after:avoid}.card,tr,.topic{break-inside:avoid}
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
        items.append((t["inv_servers"], str(total),
                      t["inv_roles"].format(primary=primary, replica=replica) if known else ""))
        versions = sorted({short_version(n["server_version"]) for n in known})
        items.append((t["inv_version"], ", ".join(versions) or t["inv_unknown"], partial(len(known))))
        if hosts:
            cores = sum(n["logical_cpu_count"] or 0 for n in hosts)
            memory = sum(n["memory_total_bytes"] or 0 for n in hosts)
            items.append((t["inv_cpu"], t["inv_cores"].format(n=cores), partial(len(hosts))))
            items.append((t["inv_memory"], fmt_bytes(memory), partial(len(hosts))))
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
        rows = [[e(n["name"]), e(role_of(n, t)), e(os_text(n)),
                 e(t["inv_cores"].format(n=n["logical_cpu_count"]) if n["logical_cpu_count"] else ""),
                 e(fmt_bytes(n["memory_total_bytes"]) if n["memory_total_bytes"] else ""),
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
            value = badge("ok", t["impact_none"]) if s_["checked"] else badge(
                "unknown", t["impact_not_checked"])
        rows.append(f'<div class="name" title="{e(localized(entry, lang, "description"))}">'
                    f'{e(name)}</div><div class="val">{value}</div>')
    note = ('<p class="note">' + e(t["scope_note"])
            + (f' {e(t["impact_note"])}' if data["findings"] else "") + "</p>")
    return f"<h2>{e(t['impact_title'])}</h2><div class=\"impact\">{''.join(rows)}</div>" + note


def render_topics(data, lang, t):
    rows = []
    for key, topic in topic_summary(data):
        entry = data["topics"].get(key)
        name = localized(entry, lang, "name") if entry else key
        status = topic["status"]
        if status == "ok":
            # Built from the rules' own scoped statements: no claim beyond what was checked.
            text = " ".join(healthy_text(data, r, lang, t) for r in topic["results"]
                            if r["outcome"] == "HEALTHY")
        elif status == "unknown":
            text = t["topic_unknown_text"]
        else:
            text = "; ".join(rule_text(data, r["rule_id"], lang, "NAME", r["rule_name"])
                             for r in topic["results"] if r["outcome"] == "ATTENTION_REQUIRED")
        rows.append(f'<div class="topic"><span class="name">{e(name)}</span>'
                    f'{badge(status, t["topic_" + status])}<span class="text">{e(text)}</span></div>')
    return (f"<h2>{e(t['topics_title'])}</h2>" + "".join(rows)
            + f'<p class="note">{e(t["scope_note"])}</p>')


def problem_rows(data, rule_id, lang, t, findings, short):
    """What is happening, likely causes, why it matters, what to do: shared by both parts."""
    causes = rule_text(data, rule_id, lang, "CAUSES")
    rows = [(t["what_happens"] if short else t["meaning"],
             render_text(rule_text(data, rule_id, lang, "MEANING"), short)),
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
        name = rule_text(data, result["rule_id"], lang, "NAME", result["rule_name"])
        cards.append(
            f'<div class="card {e(worst)}"><h3>{badge(worst, t["severity"].get(worst, worst))}'
            f"{e(name)}<span class=\"note\">{len(findings)} {e(t['findings_word'])}</span></h3><dl>"
            + problem_rows(data, result["rule_id"], lang, t, findings, short=True)
            + "</dl></div>")
    return f"<h2>{e(t['problems_title'])}</h2>" + (
        "".join(cards) or f'<p class="note">{e(t["no_problems"])}</p>')


def render_executive(data, lang, t):
    counts, verdict = summarize(data)
    tiles = [(counts["critical"], t["count_critical"]), (counts["warning"], t["count_warning"]),
             (counts["healthy"], t["count_healthy"]), (counts["not_assessed"], t["count_not_assessed"])]
    coverage = e(t["coverage"].format(**counts)) + (
        f" · {e(t['not_assessed_note'].format(count=counts['not_assessed']))}"
        if counts["not_assessed"] else "")
    collections = data["collections"]
    ok = sum(1 for c in collections if c["status"] in ("SUCCESS", "PARTIAL_SUCCESS"))
    if collections and ok < len(collections):
        errors = sorted({c["status_message"] for c in collections
                         if c["status"] not in ("SUCCESS", "PARTIAL_SUCCESS") and c["status_message"]})
        coverage += ("<br>" + e(t["collection_summary"].format(ok=ok, total=len(collections)))
                     + (f" · {e(t['collection_errors'])}: {e('; '.join(errors[:3]))}" if errors else ""))
    return (f'<div class="part">{e(t["part_exec"])}</div>'
            f'<div class="verdict v-{verdict}">{e(t["verdict_" + verdict])}</div>'
            f'<p class="note">{coverage}</p><div class="tiles">'
            + "".join(f'<div class="tile"><div class="n">{n}</div><div class="l">{e(label)}</div></div>'
                      for n, label in tiles)
            + "</div>" + render_main_problems(data, lang, t) + render_inventory(data, t)
            + render_impact_chart(data, lang, t) + render_topics(data, lang, t))


def render_system(data, t):
    parts = [f"<h2>{e(t['system'])}</h2>"]
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
            rows.append([e(n["name"]),
                         e(f"{n['server_address']}:{n['server_port']}" if n["server_address"] else ""),
                         e(role), version_cell(n["server_version"]),
                         e(fmt_uptime(n["postmaster_start_time"], data["as_of"], t)),
                         e(os_text(n)), e(n["logical_cpu_count"]), e(fmt_bytes(n["memory_total_bytes"]))])
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
             for s in data["storage"]], numeric=(2, 3, 4)))
    parts.append(f"<h3>{e(t['databases'])}</h3>")
    if data["databases"]:
        parts.append(table(
            [t["database"], t["owner"], t["size"]],
            [[e(d["database_name"]), e(d["database_owner"]), e(fmt_bytes(d["database_size_bytes"]))]
             for d in data["databases"]], numeric=(2,)))
    else:
        parts.append(missing)
    return "".join(parts)


DETAIL_LABELS = (("node", "detail_node"), ("mount_point", "detail_mount"),
                 ("data_directory", "detail_data_directory"), ("usage", "detail_usage"),
                 ("slot_name", "detail_slot"), ("slot_type", "detail_slot_type"),
                 ("wal_status", "detail_wal_status"), ("synchronous_standby_names", "detail_sync_names"),
                 ("application", "detail_application"), ("user", "detail_user"),
                 ("database", "detail_database"), ("client_addr", "detail_client"),
                 ("state", "detail_state"), ("sync_state", "detail_sync_state"),
                 ("wal_behind", "detail_wal_behind"), ("apply_delay", "detail_apply_delay"),
                 ("beyond_delay", "detail_beyond_delay"))


TIME_LABELS = (("transaction_start", "detail_transaction_start"),
               ("state_change", "detail_state_change"),
               ("captured_at", "detail_captured_at"))


def fmt_clock(value):
    """ISO time from finding details -> 'YYYY-MM-DD HH:MM:SS' (local to the repository)."""
    try:
        return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return str(value)


def render_instance(f, t):
    """One finding: technical text, measured value, subject and context (who / where)."""
    facts = []
    if f["observed_value"] is not None:
        facts.append(f"{e(t['observed'])}: <b>{e(fmt_observed(f['observed_value'], f['observed_unit'], t))}</b>")
    if f["subject_identifier"]:
        facts.append(f"{e(t['subject'])}: {e(f['subject_type'] or '')} {e(f['subject_identifier'])}")
    details = dict(f["details"] or {})
    for key in ("apply_delay", "beyond_delay"):
        if details.get(key + "_seconds") is not None:
            details[key] = fmt_duration(float(details[key + "_seconds"]), t)
    if details.get("wal_behind_bytes") is not None:
        details["wal_behind"] = fmt_bytes(details["wal_behind_bytes"])
    if details.get("total_bytes"):
        details["usage"] = fmt_used_of(details.get("used_bytes") or 0, details["total_bytes"])
    if details.get("client_hostname"):
        details["client_addr"] = " ".join(
            x for x in (details.get("client_addr"), f"({details['client_hostname']})") if x)
    context = [f"{e(t[label])}: <b>{e(details[key])}</b>" for key, label in DETAIL_LABELS
               if details.get(key)]
    times = [f"{e(t[label])}: {e(fmt_clock(details[key]))}" for key, label in TIME_LABELS
             if details.get(key)]
    query = (f'<div class="facts">{e(t["detail_last_query"])}: '
             f'<code>{e(details["last_query"])}</code></div>' if details.get("last_query") else "")
    return (f'<div class="instance">{badge(f["severity"], t["severity"].get(f["severity"], f["severity"]))} '
            f"{e(f['finding_text'])}"
            + (f'<div class="facts">{" · ".join(facts)}</div>' if facts else "")
            + (f'<div class="facts">{" · ".join(context)}</div>' if context else "")
            + (f'<div class="facts">{" · ".join(times)}</div>' if times else "")
            + query + "</div>")


def render_findings_detail(data, lang, t):
    cards = []
    for result, findings in findings_by_rule(data):
        worst = min((f["severity"] for f in findings), key=lambda s: SEVERITY_ORDER.get(s, 9))
        rid = result["rule_id"]
        cards.append(
            f'<div class="card {e(worst)}"><h3>{e(rule_text(data, rid, lang, "NAME", result["rule_name"]))}'
            f'<span class="rule">{e(result["rule_key"])}</span></h3>'
            + (f'<div class="facts">{e(threshold_line(result, t))}</div>' if threshold_line(result, t) else "")
            + "<dl>"
            + problem_rows(data, rid, lang, t, findings, short=False)
            + "</dl>" + "".join(render_instance(f, t) for f in findings) + "</div>")
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
                note = threshold_line(r, t)
            else:
                note = explain_reason(r["reason"], data, t)
            rows.append([e(topic_name), f'{e(name)} <span class="rule">{e(r["rule_key"])}</span>',
                         badge(r["outcome"], t["outcome"].get(r["outcome"], r["outcome"])), e(note)])
    return f"<h2>{e(t['results'])}</h2>" + table(
        [t["area"], t["rule"], t["status"], ""], rows)


def render_collections(data, t):
    purpose = {"EVIDENCE": t["purpose_evidence"], "CONTEXT": t["purpose_context"]}
    return f"<h2>{e(t['collection'])}</h2>" + table(
        [t["collector"], t["node"], t["purpose"], t["status"]],
        [[e(c["collector_key"]), e(c["target_name"]), e(purpose.get(c["purpose"], c["purpose"])),
          badge(c["status"], t["collection_status"].get(c["status"], c["status"])) + (
              f'<div class="facts">{e(c["status_message"])}</div>' if c["status_message"] else "")]
         for c in data["collections"]])


def render_technical(data, lang, t):
    return (f'<div class="part part-tech">{e(t["part_tech"])}</div>'
            + render_system(data, t) + render_findings_detail(data, lang, t)
            + render_results(data, lang, t) + render_collections(data, t)
            + f"<h2>{e(t['method'])}</h2><p>{e(t['method_text'])}</p>")


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
