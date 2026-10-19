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
        "coverage": "{evaluated} / {total} kontrol değerlendirildi",
        "not_assessed_note": "{count} kontrol yeterli veri olmadığı için değerlendirilemedi.",
        "count_findings": "Bulgu", "count_critical": "Kritik", "count_warning": "Uyarı",
        "count_healthy": "Sağlıklı", "count_not_assessed": "Değerlendirilemedi",
        "impact_title": "Etkilenen alanlar",
        "impact_none": "Sorun yok", "impact_not_checked": "Bu kontrolde incelenmedi",
        "findings_word": "bulgu",
        "topics_title": "Alanlara göre durum",
        "topic_ok": "Sorun yok", "topic_attention": "Dikkat", "topic_critical": "Kritik",
        "topic_unknown": "Değerlendirilemedi",
        "topic_unknown_text": "Yeterli veri toplanamadığı için değerlendirilemedi.",
        "problems_title": "Öne çıkan sorunlar", "no_problems": "Öne çıkan bir sorun yok.",
        "why_it_matters": "Neden önemli", "what_to_do": "Ne yapılmalı", "cause": "Olası sebep",
        "system": "Sistem Bilgisi",
        "nodes": "Sunucular", "node": "Sunucu", "address": "Adres", "role": "Rol",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Çalışma süresi", "os": "İşletim sistemi", "cpu": "CPU", "memory": "Bellek",
        "storage": "Disk kullanımı", "mount": "Bağlama noktası", "used": "Kullanılan",
        "total": "Toplam",
        "databases": "Veritabanları", "database": "Veritabanı", "owner": "Sahip", "size": "Boyut",
        "findings": "Bulgular", "no_findings": "Bulgu yok.",
        "meaning": "Anlamı", "impact": "Etkisi", "recommendation": "Öneri",
        "observed": "Ölçülen", "subject": "Konu",
        "detail_application": "Uygulama", "detail_user": "Kullanıcı", "detail_database": "Veritabanı",
        "detail_client": "İstemci", "detail_state": "Durum", "detail_last_query": "Son sorgu",
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
        "days": "gün", "hours": "saat",
    },
    "en": {
        "title": "Database Health Check Report",
        "target": "System", "date": "Date", "check_no": "Check no", "requested_by": "Requested by",
        "part_exec": "Executive Summary", "part_tech": "Technical Details",
        "verdict_critical": "There are problems that need immediate action.",
        "verdict_warning": "There are problems that need attention.",
        "verdict_healthy": "No problems were found in the assessed areas.",
        "verdict_none": "No check could be evaluated; data could not be collected.",
        "coverage": "{evaluated} of {total} checks evaluated",
        "not_assessed_note": "{count} check(s) could not be evaluated for lack of data.",
        "count_findings": "Findings", "count_critical": "Critical", "count_warning": "Warning",
        "count_healthy": "Healthy", "count_not_assessed": "Not assessed",
        "impact_title": "Affected areas",
        "impact_none": "No problems", "impact_not_checked": "Not covered by this check",
        "findings_word": "finding(s)",
        "topics_title": "Status by area",
        "topic_ok": "No problems", "topic_attention": "Attention", "topic_critical": "Critical",
        "topic_unknown": "Not assessed",
        "topic_unknown_text": "Could not be assessed; not enough data was collected.",
        "problems_title": "Main problems", "no_problems": "No problems to highlight.",
        "why_it_matters": "Why it matters", "what_to_do": "What to do", "cause": "Likely cause",
        "system": "System Overview",
        "nodes": "Servers", "node": "Server", "address": "Address", "role": "Role",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Uptime", "os": "Operating system", "cpu": "CPU", "memory": "Memory",
        "storage": "Disk usage", "mount": "Mount point", "used": "Used", "total": "Total",
        "databases": "Databases", "database": "Database", "owner": "Owner", "size": "Size",
        "findings": "Findings", "no_findings": "No findings.",
        "meaning": "Meaning", "impact": "Impact", "recommendation": "Recommendation",
        "observed": "Observed", "subject": "Subject",
        "detail_application": "Application", "detail_user": "User", "detail_database": "Database",
        "detail_client": "Client", "detail_state": "State", "detail_last_query": "Last query",
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
        "days": "days", "hours": "hours",
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
            "SELECT d.topic_key, d.display_order, t.language_code, t.name, t.healthy_text "
            "FROM keystone.dictionary_topic d JOIN keystone.dictionary_topic_text t USING (topic_key)"):
        topic = topics.setdefault(r["topic_key"], {"order": r["display_order"], "text": {}})
        topic["text"][r["language_code"]] = {"name": r["name"], "healthy": r["healthy_text"]}

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

    results = conn.execute(
        """
        SELECT ad.assessment_key, rd.rule_id, rd.rule_key, rd.name AS rule_name, rd.topic_key,
               res.outcome, res.max_severity, res.reason, ar.assessment_run_id
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
               hs.memory_total_bytes, hs.captured_at AS host_captured_at
        FROM keystone.target t
        LEFT JOIN postgresql.instance_inventory ii ON ii.target_id = t.target_id
        LEFT JOIN LATERAL (
            SELECT * FROM postgresql.host_snapshot h
            WHERE h.target_id = t.target_id AND h.captured_at <= %s
            ORDER BY h.captured_at DESC LIMIT 1
        ) hs ON TRUE
        WHERE (t.parent_target_id = %s AND t.target_type = 'NODE' AND t.is_active)
           OR (t.target_id = %s AND t.target_type = 'NODE')
        ORDER BY t.target_id
        """, (as_of, check["target_id"], check["target_id"])).fetchall()

    storage = conn.execute(
        """
        SELECT t.name AS node_name, s.mount_point, s.used_bytes, s.total_bytes
        FROM keystone.target t
        JOIN LATERAL (
            SELECT max(captured_at) AS captured_at FROM postgresql.storage_snapshot
            WHERE target_id = t.target_id AND captured_at <= %s
        ) last ON last.captured_at IS NOT NULL
        JOIN postgresql.storage_snapshot s
            ON s.target_id = t.target_id AND s.captured_at = last.captured_at
        WHERE (t.parent_target_id = %s AND t.target_type = 'NODE' AND t.is_active)
           OR (t.target_id = %s AND t.target_type = 'NODE')
        ORDER BY t.target_id, s.mount_point
        """, (as_of, check["target_id"], check["target_id"])).fetchall()

    databases = conn.execute(
        """
        SELECT d.database_name, d.database_owner, d.database_size_bytes
        FROM postgresql.database_snapshot d
        WHERE d.target_id = %s
          AND d.captured_at = (SELECT max(captured_at) FROM postgresql.database_snapshot
                               WHERE target_id = %s AND captured_at <= %s)
          AND NOT COALESCE(d.is_template, FALSE)
        ORDER BY d.database_size_bytes DESC NULLS LAST, d.database_name
        """, (check["target_id"], check["target_id"], as_of)).fetchall()

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
    seconds = max((as_of - start).total_seconds(), 0)
    days, hours = int(seconds // 86400), int(seconds % 86400 // 3600)
    return f"{days} {t['days']} {hours} {t['hours']}"


def fmt_observed(value, unit):
    if value is None:
        return ""
    number = f"{value:,.0f}" if value == int(value) else f"{value:,.2f}"
    return f"{number} {unit or ''}".strip()


def first_sentence(text):
    """First sentence of a Dictionary text, for the short executive view."""
    if not text:
        return ""
    match = re.search(r"(?<=[.!?])\s", text)
    return text[:match.start()] if match else text


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
    for f in data["findings"]:
        if f["severity"] == "CRITICAL":
            counts["critical"] += 1
        elif f["severity"] == "WARNING":
            counts["warning"] += 1
    counts["findings"] = len(data["findings"])
    counts["evaluated"] = counts["healthy"] + counts["attention"]

    if counts["critical"]:
        verdict = "critical"
    elif counts["findings"]:
        verdict = "warning"
    elif counts["evaluated"]:
        verdict = "healthy"
    else:
        verdict = "none"
    return counts, verdict


def impact_summary(data):
    """Per category: findings by severity and whether any of its rules was evaluated."""
    evaluated = {r["rule_id"] for r in data["results"]
                 if r["outcome"] in ("HEALTHY", "ATTENTION_REQUIRED")}
    summary = {key: {"CRITICAL": 0, "WARNING": 0, "INFO": 0, "checked": False}
               for key in data["categories"]}
    for rule_id, keys in data["rule_categories"].items():
        for key in keys:
            if rule_id in evaluated and key in summary:
                summary[key]["checked"] = True
    for f in data["findings"]:
        for key in data["rule_categories"].get(f["rule_id"], ()):
            if key in summary:
                summary[key][f["severity"]] = summary[key].get(f["severity"], 0) + 1
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
--na:#5b6575;--na-bg:#eef0f3;--crit-bar:#d92d20;--warn-bar:#e0a100}
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
.impact{display:grid;grid-template-columns:minmax(120px,170px) 1fr minmax(110px,auto);gap:8px 14px;align-items:center}
.impact .name{font-weight:600}
.impact .track{height:14px;display:flex;gap:2px}
.impact .seg{height:14px}
.impact .seg:first-child{border-radius:4px 0 0 4px}.impact .seg:last-child{border-radius:0 4px 4px 0}
.impact .seg:only-child{border-radius:4px}
.seg.CRITICAL{background:var(--crit-bar)}.seg.WARNING{background:var(--warn-bar)}.seg.INFO{background:#98a2b3}
.impact .val{font-size:14px;color:var(--muted);white-space:nowrap}
.legend{display:flex;gap:16px;font-size:13px;color:var(--muted);margin-top:10px}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:-1px}
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
.instance{background:var(--soft);border-radius:4px;padding:8px 10px;margin-top:8px;font-size:14px}
.instance code{font-family:Consolas,monospace;font-size:12px;white-space:pre-wrap;word-break:break-word}
.facts{color:var(--muted);font-size:13px;margin-top:4px}
.rule{color:var(--muted);font-size:12px;font-family:Consolas,monospace;white-space:nowrap}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media (max-width:640px){main{padding:24px 16px 48px}h1{font-size:22px}
table{display:block;overflow-x:auto}.topic{grid-template-columns:1fr auto}.topic .text{grid-column:1/-1}
.impact{grid-template-columns:110px 1fr}.impact .val{grid-column:2}.card dl{grid-template-columns:1fr}}
@media print{main{padding:0;max-width:none}h2{break-after:avoid}.card,tr,.topic{break-inside:avoid}
.part-tech{break-before:page}body{font-size:12px}
.seg,.legend i{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
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


def render_impact_chart(data, lang, t):
    """Horizontal bars: findings per impact category, split by severity; labels carry the values."""
    summary = impact_summary(data)
    biggest = max([sum(s[k] for k in SEVERITY_ORDER) for s in summary.values()] + [1])
    rows = []
    for key, entry in sorted(data["categories"].items(), key=lambda item: item[1]["order"]):
        s = summary[key]
        total = sum(s[k] for k in SEVERITY_ORDER)
        name = localized(entry, lang, "name")
        if total:
            segments = "".join(
                f'<div class="seg {sev}" style="width:{100 * s[sev] / biggest:.1f}%" '
                f'title="{e(name)}: {s[sev]} {e(t["severity"][sev])}"></div>'
                for sev in SEVERITY_ORDER if s[sev])
            value = f"{total} {e(t['findings_word'])}"
        else:
            segments = ""
            value = badge("ok", t["impact_none"]) if s["checked"] else badge(
                "unknown", t["impact_not_checked"])
        rows.append(f'<div class="name" title="{e(localized(entry, lang, "description"))}">'
                    f"{e(name)}</div><div class=\"track\">{segments}</div>"
                    f'<div class="val">{value}</div>')
    legend = ('<div class="legend">'
              f'<span><i style="background:var(--crit-bar)"></i>{e(t["severity"]["CRITICAL"])}</span>'
              f'<span><i style="background:var(--warn-bar)"></i>{e(t["severity"]["WARNING"])}</span>'
              "</div>")
    return (f"<h2>{e(t['impact_title'])}</h2><div class=\"impact\">{''.join(rows)}</div>"
            + (legend if data["findings"] else ""))


def render_topics(data, lang, t):
    rows = []
    for key, topic in topic_summary(data):
        entry = data["topics"].get(key)
        name = localized(entry, lang, "name") if entry else key
        status = topic["status"]
        if status == "ok":
            text = localized(entry, lang, "healthy") if entry else ""
        elif status == "unknown":
            text = t["topic_unknown_text"]
        else:
            text = "; ".join(rule_text(data, r["rule_id"], lang, "NAME", r["rule_name"])
                             for r in topic["results"] if r["outcome"] == "ATTENTION_REQUIRED")
        rows.append(f'<div class="topic"><span class="name">{e(name)}</span>'
                    f'{badge(status, t["topic_" + status])}<span class="text">{e(text)}</span></div>')
    return f"<h2>{e(t['topics_title'])}</h2>" + "".join(rows)


def render_main_problems(data, lang, t):
    cards = []
    for result, findings in findings_by_rule(data):
        worst = min((f["severity"] for f in findings), key=lambda s: SEVERITY_ORDER.get(s, 9))
        name = rule_text(data, result["rule_id"], lang, "NAME", result["rule_name"])
        cards.append(
            f'<div class="card {e(worst)}"><h3>{badge(worst, t["severity"].get(worst, worst))}'
            f"{e(name)}<span class=\"note\">{len(findings)} {e(t['findings_word'])}</span></h3><dl>"
            f"<dt>{e(t['cause'])}</dt><dd>{e(first_sentence(rule_text(data, result['rule_id'], lang, 'MEANING')))}</dd>"
            f"<dt>{e(t['why_it_matters'])}</dt><dd>{e(first_sentence(rule_text(data, result['rule_id'], lang, 'IMPACT')))}</dd>"
            f"<dt>{e(t['what_to_do'])}</dt><dd>{e(first_sentence(rule_text(data, result['rule_id'], lang, 'RECOMMENDATION', findings[0]['recommendation'])))}</dd>"
            "</dl></div>")
    return f"<h2>{e(t['problems_title'])}</h2>" + (
        "".join(cards) or f'<p class="note">{e(t["no_problems"])}</p>')


def render_executive(data, lang, t):
    counts, verdict = summarize(data)
    tiles = [(counts["findings"], t["count_findings"]), (counts["critical"], t["count_critical"]),
             (counts["warning"], t["count_warning"]), (counts["healthy"], t["count_healthy"]),
             (counts["not_assessed"], t["count_not_assessed"])]
    coverage = e(t["coverage"].format(**counts)) + (
        f" · {e(t['not_assessed_note'].format(count=counts['not_assessed']))}"
        if counts["not_assessed"] else "")
    return (f'<div class="part">{e(t["part_exec"])}</div>'
            f'<div class="verdict v-{verdict}">{e(t["verdict_" + verdict])}</div>'
            f'<p class="note">{coverage}</p><div class="tiles">'
            + "".join(f'<div class="tile"><div class="n">{n}</div><div class="l">{e(label)}</div></div>'
                      for n, label in tiles)
            + "</div>" + render_impact_chart(data, lang, t) + render_topics(data, lang, t)
            + render_main_problems(data, lang, t))


def render_system(data, t):
    parts = [f"<h2>{e(t['system'])}</h2>"]
    if data["nodes"]:
        rows = []
        for n in data["nodes"]:
            role = "" if n["in_recovery"] is None else (
                t["role_replica"] if n["in_recovery"] else t["role_primary"])
            os_text = n["os_name"] or ""
            if n["os_version"] and n["os_version"] not in os_text:   # "Ubuntu 24.04.4 LTS" already has it
                os_text = f"{os_text} {n['os_version']}".strip()
            rows.append([e(n["name"]),
                         e(f"{n['server_address']}:{n['server_port']}" if n["server_address"] else ""),
                         e(role), e(n["server_version"]),
                         e(fmt_uptime(n["postmaster_start_time"], data["as_of"], t)),
                         e(os_text), e(n["logical_cpu_count"]), e(fmt_bytes(n["memory_total_bytes"]))])
        parts.append(f"<h3>{e(t['nodes'])}</h3>" + table(
            [t["node"], t["address"], t["role"], t["version"], t["up_since"], t["os"], t["cpu"],
             t["memory"]], rows, numeric=(6, 7)))
    if data["storage"]:
        parts.append(f"<h3>{e(t['storage'])}</h3>" + table(
            [t["node"], t["mount"], t["used"], t["total"], "%"],
            [[e(s["node_name"]), e(s["mount_point"]), e(fmt_bytes(s["used_bytes"])),
              e(fmt_bytes(s["total_bytes"])),
              e(f"{100 * s['used_bytes'] / s['total_bytes']:.0f}%" if s["total_bytes"] else "")]
             for s in data["storage"]], numeric=(2, 3, 4)))
    if data["databases"]:
        parts.append(f"<h3>{e(t['databases'])}</h3>" + table(
            [t["database"], t["owner"], t["size"]],
            [[e(d["database_name"]), e(d["database_owner"]), e(fmt_bytes(d["database_size_bytes"]))]
             for d in data["databases"]], numeric=(2,)))
    return "".join(parts)


DETAIL_LABELS = (("application", "detail_application"), ("user", "detail_user"),
                 ("database", "detail_database"), ("client_addr", "detail_client"),
                 ("state", "detail_state"))


def render_instance(f, t):
    """One finding: technical text, measured value, subject and context (who / where)."""
    facts = []
    if f["observed_value"] is not None:
        facts.append(f"{e(t['observed'])}: {e(fmt_observed(f['observed_value'], f['observed_unit']))}")
    if f["subject_identifier"]:
        facts.append(f"{e(t['subject'])}: {e(f['subject_type'] or '')} {e(f['subject_identifier'])}")
    details = dict(f["details"] or {})
    if details.get("client_hostname"):
        details["client_addr"] = " ".join(
            x for x in (details.get("client_addr"), f"({details['client_hostname']})") if x)
    context = [f"{e(t[label])}: <b>{e(details[key])}</b>" for key, label in DETAIL_LABELS
               if details.get(key)]
    query = (f'<div class="facts">{e(t["detail_last_query"])}: '
             f'<code>{e(details["last_query"])}</code></div>' if details.get("last_query") else "")
    return (f'<div class="instance">{badge(f["severity"], t["severity"].get(f["severity"], f["severity"]))} '
            f"{e(f['finding_text'])}"
            + (f'<div class="facts">{" · ".join(facts)}</div>' if facts else "")
            + (f'<div class="facts">{" · ".join(context)}</div>' if context else "")
            + query + "</div>")


def render_findings_detail(data, lang, t):
    cards = []
    for result, findings in findings_by_rule(data):
        worst = min((f["severity"] for f in findings), key=lambda s: SEVERITY_ORDER.get(s, 9))
        rid = result["rule_id"]
        cards.append(
            f'<div class="card {e(worst)}"><h3>{e(rule_text(data, rid, lang, "NAME", result["rule_name"]))}'
            f'<span class="rule">{e(result["rule_key"])}</span></h3><dl>'
            f"<dt>{e(t['meaning'])}</dt><dd>{e(rule_text(data, rid, lang, 'MEANING'))}</dd>"
            f"<dt>{e(t['impact'])}</dt><dd>{e(rule_text(data, rid, lang, 'IMPACT'))}</dd>"
            f"<dt>{e(t['recommendation'])}</dt><dd>{e(rule_text(data, rid, lang, 'RECOMMENDATION', findings[0]['recommendation']))}</dd>"
            "</dl>" + "".join(render_instance(f, t) for f in findings) + "</div>")
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
                note = rule_text(data, r["rule_id"], lang, "HEALTHY")
            elif r["outcome"] == "ATTENTION_REQUIRED":
                note = ""
            else:
                note = r["reason"] or ""
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
    body = (render_header(data, t) + render_executive(data, lang, t) + render_technical(data, lang, t)
            + f"<footer>{e(t['generated'])}: {e(fmt_time(datetime.now(timezone.utc).astimezone()))}"
            " · Keystone</footer>")
    return (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(t['title'])} - {e(data['check']['target_name'])}</title><style>{STYLE}</style>"
            f"</head><body><main>{body}</main></body></html>")


def write_report(conn, health_check_id, lang="tr", output=None):
    """Render and write the report; returns the file path."""
    if lang not in TEXTS:
        raise ValueError(f"Unsupported report language: {lang} (available: {', '.join(TEXTS)})")
    data = load_report_data(conn, health_check_id)
    path = Path(output) if output else (
        Path(DEFAULT_OUTPUT_DIR) / f"health_check_{health_check_id}_{lang}.html")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(data, lang), encoding="utf-8")
    logger.info("Report written: %s", path)
    return path


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        prog="python -m repository.report.health_check_report",
        description="Write the HTML report of a health check.",
    )
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--health-check", type=int, help="health_check_id")
    which.add_argument("--target", type=int, help="latest completed health check of this target")
    parser.add_argument("--lang", default="tr", choices=sorted(TEXTS), help="report language (default: tr)")
    parser.add_argument("--output", help=f"file path (default: {DEFAULT_OUTPUT_DIR}/health_check_<id>_<lang>.html)")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    configure_logging("report", connect=worker.connect_repository)
    with worker.connect_repository() as conn:
        check_id = args.health_check or latest_health_check_id(conn, args.target)
        write_report(conn, check_id, args.lang, args.output)


if __name__ == "__main__":
    main()
