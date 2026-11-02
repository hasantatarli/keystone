"""Configuration recommendations (ADR-0017 step 3): one calculation per setting.

Numbers come from the configuration Dictionary (config_dictionary); this module
holds the logic. Values are compared in Keystone units: bytes, seconds, plain
numbers or words. Recommended values are written in PostgreSQL syntax (128MB,
15min) so they read the same in every language and can be pasted into a command.
"""

import math

from repository.intelligence.config_dictionary import parameter, settings_for_version

MB = 1024 ** 2
UNIT_BYTES = {"B": 1, "kB": 1024, "8kB": 8192, "16kB": 16384, "32kB": 32768, "64kB": 65536,
              "MB": MB, "GB": 1024 ** 3, "TB": 1024 ** 4}
UNIT_SECONDS = {"us": 1e-6, "ms": 0.001, "s": 1, "min": 60, "h": 3600, "d": 86400}

# Settings whose recommendation needs a fact from the host collector (SSH).
NEEDS = {"shared_buffers": "memory", "effective_cache_size": "memory", "work_mem": "memory",
         "maintenance_work_mem": "memory", "max_wal_size": "disk", "min_wal_size": "disk",
         "max_worker_processes": "cpus", "max_parallel_workers": "cpus",
         "max_parallel_workers_per_gather": "cpus", "max_parallel_maintenance_workers": "cpus"}


# Profile fields a recommendation depends on; an assumed one is said next to it.
PROFILE_DEPENDS = {
    "shared_buffers": ("dedicated",), "effective_cache_size": ("dedicated",),
    "work_mem": ("dedicated", "workload_type"), "maintenance_work_mem": ("dedicated",),
    "max_wal_size": ("workload_type",), "min_wal_size": ("workload_type",),
    "random_page_cost": ("storage_type",), "effective_io_concurrency": ("storage_type",),
}


class NotAssessed(Exception):
    """A setting cannot be recommended for this server; code names why (report texts)."""

    def __init__(self, code, status="NOT_ASSESSED"):
        super().__init__(code)
        self.code, self.status = code, status


# ----------------------------------------------------------------- values

def canonical(row, value_type):
    """A pg_settings value in Keystone units: bytes, seconds, a number or the word itself."""
    if row is None:
        return None
    value, unit = row["setting_value"], row.get("unit")
    if value_type in ("ENUM", "BOOLEAN"):
        return value
    number = float(value)
    if number < 0:
        return number                                  # -1: disabled or automatic, kept as is
    if unit in UNIT_BYTES:
        return number * UNIT_BYTES[unit]
    if unit in UNIT_SECONDS:
        return number * UNIT_SECONDS[unit]
    return number


def pg_value(value, value_type):
    """A Keystone value in PostgreSQL syntax: 4GB, 512MB, 15min, 250ms, 0.9, on."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if value < 0:
        return f"{value:g}"
    if value_type == "BYTE":
        for unit, size in (("GB", 1024 ** 3), ("MB", MB), ("kB", 1024)):
            if value >= size and value % size == 0:
                return f"{int(value // size)}{unit}"
        return f"{int(value)}B"
    if value_type == "SECOND":
        for unit, size in (("h", 3600), ("min", 60), ("s", 1)):
            if value >= size and value % size == 0:
                return f"{int(value // size)}{unit}"
        return f"{round(value * 1000)}ms"
    return f"{int(value)}" if value == int(value) else f"{value:g}"


def mb_floor(value):
    """Byte recommendations in whole megabytes."""
    return max(MB, math.floor(value / MB) * MB)


# ----------------------------------------------------------------- facts

def server_facts(evidence):
    """Primary, version and the smallest node's memory, CPUs and data disk from the evidence."""
    inventory = evidence.get("PG_INSTANCE_INVENTORY") or []
    settings = {}
    for row in evidence.get("PG_CONFIGURATION_SNAPSHOT") or []:
        settings.setdefault(row["target_id"], {})[row["setting_name"]] = row
    primary = next((n for n in inventory if not n["in_recovery"]), None)
    primary_id = primary["target_id"] if primary else min(settings, default=None)
    names = {n["target_id"]: n["node_name"] for n in inventory}
    for row in evidence.get("PG_CONFIGURATION_SNAPSHOT") or []:
        names.setdefault(row["target_id"], row["node_name"])
    host_rows = evidence.get("PG_HOST_SNAPSHOT") or []
    hosts = {r["target_id"]: r for r in host_rows if r.get("record_type") == "HOST"}
    disks = {}
    from repository.intelligence.assessment_engine import data_mount
    for target_id, node_settings in settings.items():
        directory = node_settings.get("data_directory", {}).get("setting_value")
        mounts = [r for r in host_rows if r.get("record_type", "STORAGE") == "STORAGE"
                  and r["target_id"] == target_id and r.get("total_bytes")]
        mount = data_mount(directory, mounts)
        if mount:
            disks[target_id] = mount["total_bytes"]
    with_memory = [hosts[t] for t in settings if t in hosts and hosts[t].get("memory_total_bytes")]
    with_cpus = [hosts[t] for t in settings if t in hosts and hosts[t].get("logical_cpu_count")]
    version = None
    if primary and primary.get("server_version"):
        version = int(str(primary["server_version"]).split(".")[0])
    return {
        "primary_id": primary_id,
        "version": version,
        "names": names,
        "settings": settings,
        "memory": min((h["memory_total_bytes"] for h in with_memory), default=None),
        "memory_node": min(with_memory, key=lambda h: h["memory_total_bytes"])["target_id"] if with_memory else None,
        "cpus": min((h["logical_cpu_count"] for h in with_cpus), default=None),
        "disk": min(disks.values(), default=None),
        "nodes_without_host": sorted(names[t] for t in settings if t not in hosts),
    }


# ----------------------------------------------------------------- calculations

def recommend(dictionary, facts, profile):
    """One result per setting the server's version has: status, current, recommended, range, calculation."""
    workload = profile["workload_type"]["value"]
    storage = profile["storage_type"]["value"]
    dedicated = profile["dedicated"]["value"]
    version = facts["version"]
    primary = facts["settings"].get(facts["primary_id"], {})
    recommended_so_far = {}
    results = []

    for setting in settings_for_version(dictionary, version):
        key, value_type = setting["setting_key"], setting["value_type"]
        used = {}

        def p(name, setting_key=key):
            value = parameter(dictionary, setting_key, name, workload, storage, version)
            if value is not None:
                used[name if setting_key == key else f"general.{name}"] = value
            return value

        current = canonical(primary.get(key), value_type)
        assumed = [f for f in PROFILE_DEPENDS.get(key, ()) if profile[f].get("assumed")]
        result = {"setting_key": key, "group_key": setting["group_key"], "value_type": value_type,
                  "current_value": current, "recommended_value": None, "acceptable": None,
                  "calculation": None, "reason_code": None, "parameters_used": used,
                  "node_differences": node_differences(facts, key, value_type),
                  "restart_required": (primary.get(key) or {}).get("context") == "postmaster"
                  if primary.get(key) else None,
                  "assumptions": assumed or None}
        try:
            if current is None:
                raise NotAssessed("setting_not_collected")
            recommended, calculation = CALCULATIONS.get(key, fixed_value)(p, facts, dedicated, recommended_so_far)
            recommended_so_far[key] = recommended
            acceptable = acceptable_range(p, recommended)
            result.update(recommended_value=recommended, acceptable=acceptable, calculation=calculation,
                          status="FITS" if fits(current, acceptable) else "DEVIATES")
        except NotAssessed as exc:
            result.update(status=exc.status, reason_code=exc.code)
        results.append(result)
    return results


def available_memory(p, facts, dedicated):
    if facts["memory"] is None:
        raise NotAssessed("no_memory")
    share = 1.0 if dedicated else p("non_dedicated_memory_share", None)
    return facts["memory"] * share, share


def memory_share(p, facts, dedicated, _):
    memory, dedicated_share = available_memory(p, facts, dedicated)
    value = memory * p("memory_share")
    low, high = p("min"), p("max")
    value = max(value, low) if low is not None else value
    value = min(value, high) if high is not None else value
    return mb_floor(value), {"method": "memory_share", "memory": facts["memory"],
                             "dedicated_share": dedicated_share, "share": p("memory_share"),
                             "min": low, "max": high}


def work_mem(p, facts, dedicated, so_far):
    memory, dedicated_share = available_memory(p, facts, dedicated)
    connections = canonical(facts["settings"].get(facts["primary_id"], {}).get("max_connections"), "COUNT")
    if not connections:
        raise NotAssessed("setting_not_collected")
    shared_buffers = so_far.get("shared_buffers") or 0
    factor = p("connection_factor")
    value = (memory - shared_buffers) / (connections * factor)
    value = min(max(value, p("min")), p("max"))
    return mb_floor(value), {"method": "work_mem", "memory": facts["memory"], "dedicated_share": dedicated_share,
                             "shared_buffers": shared_buffers, "max_connections": connections, "factor": factor,
                             "min": p("min"), "max": p("max")}


def max_wal_size(p, facts, dedicated, _):
    if facts["disk"] is None:
        raise NotAssessed("no_disk")
    value, cap = p("value"), facts["disk"] * p("max_disk_share")
    return mb_floor(min(value, cap)), {"method": "max_wal_size", "value": value, "disk": facts["disk"],
                                       "disk_share": p("max_disk_share"), "capped": cap < value}


def min_wal_size(p, facts, dedicated, so_far):
    base = so_far.get("max_wal_size")
    if base is None:
        raise NotAssessed("no_disk")
    return mb_floor(base * p("max_wal_size_share")), {"method": "share_of", "of": "max_wal_size",
                                                      "base": base, "share": p("max_wal_size_share")}


def parallel(p, facts, dedicated, _):
    if facts["cpus"] is None:
        raise NotAssessed("no_cpus")
    minimum = p("parallel_min_cpus", None)
    if facts["cpus"] < minimum:
        raise NotAssessed("few_cpus", status="NOT_APPLICABLE")
    value = math.ceil(facts["cpus"] * p("cpu_share"))
    if p("max") is not None:
        value = min(value, p("max"))
    if p("min") is not None:
        value = max(value, p("min"))
    return float(value), {"method": "cpu_share", "cpus": facts["cpus"], "share": p("cpu_share"),
                          "min": p("min"), "max": p("max")}


def fixed_value(p, facts, dedicated, _):
    value = p("value")
    if value is None:
        raise NotAssessed("no_recommendation")
    return value, {"method": "fixed"}


CALCULATIONS = {
    "shared_buffers": memory_share, "effective_cache_size": memory_share,
    "maintenance_work_mem": memory_share, "work_mem": work_mem,
    "max_wal_size": max_wal_size, "min_wal_size": min_wal_size,
    "max_worker_processes": parallel, "max_parallel_workers": parallel,
    "max_parallel_workers_per_gather": parallel, "max_parallel_maintenance_workers": parallel,
}


# ----------------------------------------------------------------- ranges

def acceptable_range(p, recommended):
    """{"values": [...]} for words, {"low", "high"} otherwise; which Dictionary keys exist decides."""
    values = p("accept_values")
    if values is not None:
        return {"values": [v.strip() for v in values.split(",")]}
    if p("accept_min") is not None:
        return {"low": p("accept_min"), "high": p("accept_max")}
    low, high = p("range_low"), p("range_high")
    return {"low": recommended * low if low is not None else None,
            "high": recommended * high if high is not None else None}


def fits(current, acceptable):
    if "values" in acceptable:
        return str(current) in acceptable["values"]
    if isinstance(current, str):
        return False
    low, high = acceptable.get("low"), acceptable.get("high")
    return (low is None or current >= low) and (high is None or current <= high)


def acceptable_text(acceptable, value_type):
    if acceptable is None:
        return ""
    if "values" in acceptable:
        return ", ".join(acceptable["values"])
    low, high = acceptable.get("low"), acceptable.get("high")
    if high is None:
        return f"≥ {pg_value(round_for(low, value_type), value_type)}"
    return f"{pg_value(round_for(low, value_type), value_type)} – {pg_value(round_for(high, value_type), value_type)}"


def round_for(value, value_type):
    if value_type == "BYTE":
        return mb_floor(value) if value >= MB else value
    if value_type == "COUNT":
        return float(round(value))
    if value_type == "SECOND":
        return round(value, 3)
    return round(value, 3)


def node_differences(facts, key, value_type):
    """Nodes whose value differs from the primary's; None when every node agrees."""
    primary = facts["settings"].get(facts["primary_id"], {}).get(key)
    if primary is None:
        return None
    differing = [{"node": facts["names"].get(target_id, str(target_id)),
                  "value": pg_value(canonical(s[key], value_type), value_type)}
                 for target_id, s in facts["settings"].items()
                 if target_id != facts["primary_id"] and key in s
                 and s[key]["setting_value"] != primary["setting_value"]]
    return differing or None
