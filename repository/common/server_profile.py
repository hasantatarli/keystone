"""Server profile of a target (ADR-0017): facts Keystone cannot collect.

NULL on the target means "not given"; the default is used and marked as assumed.
"""

PROFILE_DEFAULTS = {"workload_type": "OLTP", "dedicated": True, "storage_type": "SSD"}


def server_profile(target):
    """{field: {"value": ..., "assumed": bool}} from a target row; missing fields count as not given."""
    profile = {}
    for field, default in PROFILE_DEFAULTS.items():
        value = target.get(field)
        profile[field] = {"value": default if value is None else value, "assumed": value is None}
    return profile
