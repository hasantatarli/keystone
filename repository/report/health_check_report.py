"""Health check report as one self-contained HTML file (MVP Plan Phase 1, report).

The frame (headings, labels, summary sentences) is Turkish or English; rule
finding and recommendation texts come from the Dictionary in English. The
file has no external resources, so it can be e-mailed, opened offline and
printed.

    python -m repository.report.health_check_report --health-check 1 --lang tr
    python -m repository.report.health_check_report --target 1          # latest check
"""

import argparse
from datetime import datetime, timezone
import html
from pathlib import Path

from repository.common.logging_config import configure_logging, get_logger
from repository.worker import worker


logger = get_logger("report")

DEFAULT_OUTPUT_DIR = "reports"
SEVERITY_ORDER = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}


# -----------------------------------------------------------------------------
# Report frame texts. Add a language by adding a dictionary with the same keys.
# -----------------------------------------------------------------------------

TEXTS = {
    "tr": {
        "title": "Veritabanı Sağlık Kontrolü Raporu",
        "target": "Sistem", "date": "Tarih", "check_no": "Kontrol no", "requested_by": "Talep eden",
        "summary": "Özet",
        "verdict_critical": "Acil müdahale gerektiren bulgular var.",
        "verdict_warning": "Dikkat gerektiren bulgular var.",
        "verdict_healthy": "Değerlendirilen alanlarda sorun bulunmadı.",
        "verdict_none": "Hiçbir kural değerlendirilemedi; kanıt toplanamadı.",
        "coverage": "{evaluated} / {total} kontrol değerlendirildi",
        "not_assessed_note": "{count} kontrol yeterli kanıt olmadığı için değerlendirilemedi (aşağıda).",
        "count_findings": "Bulgu", "count_critical": "Kritik", "count_warning": "Uyarı",
        "count_healthy": "Sağlıklı", "count_not_assessed": "Değerlendirilemedi",
        "system": "Sistem Bilgisi",
        "nodes": "Sunucular", "node": "Sunucu", "address": "Adres", "role": "Rol",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Çalışma süresi", "os": "İşletim sistemi", "cpu": "CPU", "memory": "Bellek",
        "storage": "Disk kullanımı", "mount": "Bağlama noktası", "used": "Kullanılan",
        "total": "Toplam",
        "databases": "Veritabanları", "database": "Veritabanı", "owner": "Sahip", "size": "Boyut",
        "findings": "Bulgular", "no_findings": "Bulgu yok.",
        "recommendation": "Öneri", "observed": "Ölçülen", "subject": "Konu",
        "healthy": "Sağlıklı Alanlar", "no_healthy": "Sağlıklı olarak değerlendirilen kontrol yok.",
        "not_assessed": "Değerlendirilemeyen Alanlar", "reason": "Neden",
        "none": "Yok.",
        "collection": "Toplanan Veriler", "collector": "Veri kaynağı", "status": "Durum",
        "purpose_evidence": "Kanıt", "purpose_context": "Bağlam", "purpose": "Amaç",
        "method": "Yöntem",
        "method_text": ("Keystone hedef sisteme salt okunur bağlantıyla bağlanır ve yalnızca "
                        "sistem kataloglarını ve istatistik görünümlerini sorgular. Sistemde "
                        "nesne oluşturmaz, ayar değiştirmez, kurulum yapmaz. Bulgu ve öneri "
                        "metinleri İngilizcedir."),
        "generated": "Rapor oluşturma zamanı",
        "outcome": {"HEALTHY": "Sağlıklı", "ATTENTION_REQUIRED": "Dikkat",
                    "INSUFFICIENT_EVIDENCE": "Kanıt yetersiz", "ERROR": "Hata"},
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
        "summary": "Summary",
        "verdict_critical": "There are findings that need immediate action.",
        "verdict_warning": "There are findings that need attention.",
        "verdict_healthy": "No problems were found in the assessed areas.",
        "verdict_none": "No check could be evaluated; evidence could not be collected.",
        "coverage": "{evaluated} of {total} checks evaluated",
        "not_assessed_note": "{count} check(s) could not be evaluated for lack of evidence (see below).",
        "count_findings": "Findings", "count_critical": "Critical", "count_warning": "Warning",
        "count_healthy": "Healthy", "count_not_assessed": "Not assessed",
        "system": "System Overview",
        "nodes": "Servers", "node": "Server", "address": "Address", "role": "Role",
        "role_primary": "Primary", "role_replica": "Replica", "version": "PostgreSQL",
        "up_since": "Uptime", "os": "Operating system", "cpu": "CPU", "memory": "Memory",
        "storage": "Disk usage", "mount": "Mount point", "used": "Used", "total": "Total",
        "databases": "Databases", "database": "Database", "owner": "Owner", "size": "Size",
        "findings": "Findings", "no_findings": "No findings.",
        "recommendation": "Recommendation", "observed": "Observed", "subject": "Subject",
        "healthy": "Healthy Areas", "no_healthy": "No check was evaluated as healthy.",
        "not_assessed": "Areas Not Assessed", "reason": "Reason",
        "none": "None.",
        "collection": "Collected Data", "collector": "Data source", "status": "Status",
        "purpose_evidence": "Evidence", "purpose_context": "Context", "purpose": "Purpose",
        "method": "Method",
        "method_text": ("Keystone connects to the target system with read-only access and only "
                        "queries system catalogs and statistics views. It creates no objects, "
                        "changes no settings and installs nothing on the system."),
        "generated": "Report generated",
        "outcome": {"HEALTHY": "Healthy", "ATTENTION_REQUIRED": "Attention",
                    "INSUFFICIENT_EVIDENCE": "Insufficient evidence", "ERROR": "Error"},
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
        SELECT ad.assessment_key, ad.name AS assessment_name, rd.rule_id, rd.rule_key,
               rd.name AS rule_name, res.outcome, res.max_severity, res.reason,
               ar.assessment_run_id
        FROM keystone.assessment_run ar
        JOIN keystone.assessment_definition ad ON ad.assessment_id = ar.assessment_id
        JOIN keystone.assessment_result res ON res.assessment_run_id = ar.assessment_run_id
        JOIN keystone.rule_definition rd ON rd.rule_id = res.rule_id
        WHERE ar.health_check_id = %s
        ORDER BY ad.name, rd.rule_key
        """, (health_check_id,)).fetchall()

    findings = conn.execute(
        """
        SELECT f.assessment_run_id, f.rule_id, f.severity, f.title, f.finding_text,
               f.recommendation, f.observed_value, f.observed_unit,
               f.subject_type, f.subject_identifier
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
    conn.commit()

    return {"check": check, "results": results, "findings": findings,
            "collections": collections, "nodes": nodes, "storage": storage,
            "databases": databases, "as_of": as_of}


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


# -----------------------------------------------------------------------------
# Rendering
# -----------------------------------------------------------------------------

STYLE = """
:root{--ink:#1d2430;--muted:#5b6575;--line:#d9dee5;--soft:#f4f6f9;--accent:#1f4e79;
--crit:#b42318;--crit-bg:#fdecea;--warn:#93600a;--warn-bg:#fdf3df;--ok:#1e6b3a;--ok-bg:#e7f4ec;
--na:#5b6575;--na-bg:#eef0f3}
*{box-sizing:border-box}
body{margin:0;background:#fff;color:var(--ink);font:15px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif}
main{max-width:980px;margin:0 auto;padding:40px 32px 64px}
header{border-bottom:3px solid var(--accent);padding-bottom:18px;margin-bottom:28px}
.brand{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:600}
h1{font-size:26px;margin:6px 0 14px}
h2{font-size:19px;margin:36px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:20px 0 8px}
.meta{display:flex;flex-wrap:wrap;gap:6px 28px;color:var(--muted);font-size:14px}
.meta b{color:var(--ink);font-weight:600}
.verdict{padding:16px 18px;border-radius:8px;font-size:17px;font-weight:600;margin:0 0 14px}
.v-critical{background:var(--crit-bg);color:var(--crit)}
.v-warning{background:var(--warn-bg);color:var(--warn)}
.v-healthy{background:var(--ok-bg);color:var(--ok)}
.v-none{background:var(--na-bg);color:var(--na)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:14px 0}
.tile{border:1px solid var(--line);border-radius:8px;padding:10px 14px}
.tile .n{font-size:24px;font-weight:700;line-height:1.2}
.tile .l{color:var(--muted);font-size:13px}
.note{color:var(--muted);font-size:14px}
table{width:100%;border-collapse:collapse;font-size:14px;margin:6px 0 10px}
th{text-align:left;font-weight:600;color:var(--muted);border-bottom:1px solid var(--line);padding:7px 8px;background:var(--soft)}
td{border-bottom:1px solid var(--line);padding:7px 8px;vertical-align:top}
td.num,th.num{text-align:right;white-space:nowrap}
.badge{display:inline-block;border-radius:4px;padding:1px 8px;font-size:12px;font-weight:600;white-space:nowrap}
.b-CRITICAL,.b-ERROR{background:var(--crit-bg);color:var(--crit)}
.b-WARNING,.b-ATTENTION_REQUIRED{background:var(--warn-bg);color:var(--warn)}
.b-INFO,.b-INSUFFICIENT_EVIDENCE{background:var(--na-bg);color:var(--na)}
.b-HEALTHY,.b-SUCCESS{background:var(--ok-bg);color:var(--ok)}
.b-FAILED,.b-CONNECTION_FAILED,.b-TIMEOUT,.b-STALE{background:var(--crit-bg);color:var(--crit)}
.b-PARTIAL_SUCCESS,.b-WAIT_LIMIT{background:var(--warn-bg);color:var(--warn)}
.b-NOT_COLLECTED{background:var(--na-bg);color:var(--na)}
.finding{border:1px solid var(--line);border-left:4px solid var(--warn);border-radius:6px;padding:12px 16px;margin:10px 0}
.finding.CRITICAL{border-left-color:var(--crit)}
.finding h3{margin:0 0 6px;display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.finding .rec{background:var(--soft);border-radius:4px;padding:8px 10px;margin-top:8px}
.finding .rec b{display:block;font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}
.facts{color:var(--muted);font-size:13px;margin-top:4px}
.rule{color:var(--muted);font-size:12px;font-family:Consolas,monospace;white-space:nowrap}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font-size:13px}
@media (max-width:640px){main{padding:24px 16px 48px}h1{font-size:22px}
table{display:block;overflow-x:auto}}
@media print{main{padding:0;max-width:none}h2{break-after:avoid}.finding,tr{break-inside:avoid}
body{font-size:12px}}
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


def render_html(data, lang="tr"):
    t = TEXTS[lang]
    check = data["check"]
    counts, verdict = summarize(data)
    parts = []

    # Header
    meta = [(t["target"], check["target_name"]), (t["date"], fmt_time(check["started_at"])),
            (t["check_no"], check["health_check_id"])]
    if check["requested_by"]:
        meta.append((t["requested_by"], check["requested_by"]))
    parts.append('<header><div class="brand">Keystone</div>'
                 f"<h1>{e(t['title'])}</h1><div class=\"meta\">"
                 + "".join(f"<span>{e(label)}: <b>{e(value)}</b></span>" for label, value in meta)
                 + "</div></header>")

    # Summary
    tiles = [(counts["findings"], t["count_findings"]), (counts["critical"], t["count_critical"]),
             (counts["warning"], t["count_warning"]), (counts["healthy"], t["count_healthy"]),
             (counts["not_assessed"], t["count_not_assessed"])]
    parts.append(f"<section><h2>{e(t['summary'])}</h2>"
                 f'<div class="verdict v-{verdict}">{e(t["verdict_" + verdict])}</div>'
                 f'<p class="note">{e(t["coverage"].format(**counts))}'
                 + (f" · {e(t['not_assessed_note'].format(count=counts['not_assessed']))}"
                    if counts["not_assessed"] else "")
                 + '</p><div class="tiles">'
                 + "".join(f'<div class="tile"><div class="n">{n}</div><div class="l">{e(label)}</div></div>'
                           for n, label in tiles)
                 + "</div></section>")

    # System overview
    system = [f"<section><h2>{e(t['system'])}</h2>"]
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
        system.append(f"<h3>{e(t['nodes'])}</h3>" + table(
            [t["node"], t["address"], t["role"], t["version"], t["up_since"], t["os"], t["cpu"],
             t["memory"]], rows, numeric=(6, 7)))
    if data["storage"]:
        system.append(f"<h3>{e(t['storage'])}</h3>" + table(
            [t["node"], t["mount"], t["used"], t["total"], "%"],
            [[e(s["node_name"]), e(s["mount_point"]), e(fmt_bytes(s["used_bytes"])),
              e(fmt_bytes(s["total_bytes"])),
              e(f"{100 * s['used_bytes'] / s['total_bytes']:.0f}%" if s["total_bytes"] else "")]
             for s in data["storage"]], numeric=(2, 3, 4)))
    if data["databases"]:
        system.append(f"<h3>{e(t['databases'])}</h3>" + table(
            [t["database"], t["owner"], t["size"]],
            [[e(d["database_name"]), e(d["database_owner"]), e(fmt_bytes(d["database_size_bytes"]))]
             for d in data["databases"]], numeric=(2,)))
    system.append("</section>")
    parts.append("".join(system))

    # Findings
    rule_names = {r["rule_id"]: (r["rule_key"], r["rule_name"]) for r in data["results"]}
    findings = sorted(data["findings"], key=lambda f: SEVERITY_ORDER.get(f["severity"], 9))
    items = []
    for f in findings:
        key, name = rule_names.get(f["rule_id"], ("", ""))
        facts = []
        if f["observed_value"] is not None:
            facts.append(f"{e(t['observed'])}: {e(fmt_observed(f['observed_value'], f['observed_unit']))}")
        if f["subject_identifier"]:
            facts.append(f"{e(t['subject'])}: {e(f['subject_type'] or '')} {e(f['subject_identifier'])}")
        items.append(
            f'<div class="finding {e(f["severity"])}"><h3>{badge(f["severity"], t["severity"].get(f["severity"], f["severity"]))}'
            f'{e(f["title"])}<span class="rule">{e(key)}</span></h3>'
            f'<div>{e(f["finding_text"])}</div>'
            + (f'<div class="facts">{" · ".join(facts)}</div>' if facts else "")
            + f'<div class="rec"><b>{e(t["recommendation"])}</b>{e(f["recommendation"])}</div></div>')
    parts.append(f"<section><h2>{e(t['findings'])}</h2>"
                 + ("".join(items) or f'<p class="note">{e(t["no_findings"])}</p>') + "</section>")

    # Healthy areas
    healthy = [r for r in data["results"] if r["outcome"] == "HEALTHY"]
    parts.append(f"<section><h2>{e(t['healthy'])}</h2>" + (
        table(["", t["status"]], [
            [f'{e(r["rule_name"])} <span class="rule">{e(r["rule_key"])}</span>',
             badge("HEALTHY", t["outcome"]["HEALTHY"])] for r in healthy])
        if healthy else f'<p class="note">{e(t["no_healthy"])}</p>') + "</section>")

    # Not assessed
    missing = [r for r in data["results"] if r["outcome"] in ("INSUFFICIENT_EVIDENCE", "ERROR")]
    parts.append(f"<section><h2>{e(t['not_assessed'])}</h2>" + (
        table(["", t["status"], t["reason"]], [
            [f'{e(r["rule_name"])} <span class="rule">{e(r["rule_key"])}</span>',
             badge(r["outcome"], t["outcome"].get(r["outcome"], r["outcome"])), e(r["reason"])]
            for r in missing])
        if missing else f'<p class="note">{e(t["none"])}</p>') + "</section>")

    # Collected data
    purpose = {"EVIDENCE": t["purpose_evidence"], "CONTEXT": t["purpose_context"]}
    parts.append(f"<section><h2>{e(t['collection'])}</h2>" + table(
        [t["collector"], t["node"], t["purpose"], t["status"]],
        [[e(c["collector_key"]), e(c["target_name"]), e(purpose.get(c["purpose"], c["purpose"])),
          badge(c["status"], t["collection_status"].get(c["status"], c["status"])) + (f'<div class="facts">{e(c["status_message"])}</div>'
                                             if c["status_message"] else "")]
         for c in data["collections"]]) + "</section>")

    # Method and footer
    parts.append(f"<section><h2>{e(t['method'])}</h2><p>{e(t['method_text'])}</p></section>")
    parts.append(f"<footer>{e(t['generated'])}: {e(fmt_time(datetime.now(timezone.utc).astimezone()))}"
                 f" · Keystone</footer>")

    return (f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{e(t['title'])} - {e(check['target_name'])}</title><style>{STYLE}</style>"
            f"</head><body><main>{''.join(parts)}</main></body></html>")


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
