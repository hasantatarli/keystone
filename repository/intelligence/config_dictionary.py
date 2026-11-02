"""Configuration Dictionary (ADR-0017): which settings Keystone recommends and the numbers behind them.

The calculations themselves live in code (step 3); this module only reads the
Dictionary and picks the number that applies to a server.
"""

from psycopg.rows import dict_row

RANGE_KEYS = {"range_low", "range_high", "accept_min", "accept_max", "accept_values"}


def load_config_dictionary(conn, provider):
    """{"settings": {key: row}, "texts": {key: {lang: {type: text}}}, "parameters": [row]} of one provider."""
    with conn.cursor(row_factory=dict_row) as cur:
        settings = cur.execute(
            "SELECT setting_key, group_key, value_type, min_version, max_version, display_order "
            "FROM keystone.config_setting WHERE provider = %s ORDER BY display_order",
            (provider,)).fetchall()
        texts = cur.execute(
            "SELECT setting_key, language_code, text_type, text FROM keystone.config_setting_text "
            "WHERE provider = %s", (provider,)).fetchall()
        parameters = cur.execute(
            "SELECT setting_key, parameter_key, workload_type, storage_type, min_version, "
            "value_numeric, value_text, unit FROM keystone.config_parameter WHERE provider = %s",
            (provider,)).fetchall()
    by_setting = {}
    for t in texts:
        by_setting.setdefault(t["setting_key"], {}).setdefault(t["language_code"], {})[t["text_type"]] = t["text"]
    return {"settings": {s["setting_key"]: s for s in settings}, "texts": by_setting, "parameters": parameters}


def settings_for_version(dictionary, version):
    """Settings the server's major version has, in report order."""
    return [s for s in dictionary["settings"].values()
            if (s["min_version"] is None or s["min_version"] <= version)
            and (s["max_version"] is None or version <= s["max_version"])]


def parameter(dictionary, setting_key, parameter_key, workload_type, storage_type, version):
    """The value of the most specific matching row, or None.

    A row limited to the server's workload beats one for every workload, then storage type,
    then the latest first version. setting_key None reads a general number.
    """
    candidates = [
        p for p in dictionary["parameters"]
        if p["setting_key"] == setting_key and p["parameter_key"] == parameter_key
        and p["workload_type"] in (None, workload_type)
        and p["storage_type"] in (None, storage_type)
        and (p["min_version"] is None or p["min_version"] <= version)
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda p: (p["workload_type"] is not None,
                                          p["storage_type"] is not None, p["min_version"] or 0))
    if best["value_text"] is not None:
        return best["value_text"]
    return float(best["value_numeric"])
