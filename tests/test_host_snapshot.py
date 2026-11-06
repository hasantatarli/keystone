"""PG_HOST_SNAPSHOT output parsing (no database needed).

Run from the repository root:
    python -B -m unittest discover -s tests -p test_host_snapshot.py -v
"""

import unittest

from repository.worker import worker

# Container in the multi-system lab (2026-10-31): the data volume shares its device with "/".
OUTPUT = """===HOSTNAME===
d7659a462f0a
===OS_RELEASE===
PRETTY_NAME="Debian GNU/Linux 13 (trixie)"
NAME="Debian GNU/Linux"
===UPTIME===
3600.5 7000.1
===CPU===
1
===MEMORY===
MemTotal:        2000000 kB
MemAvailable:    1000000 kB
SwapTotal:             0 kB
SwapFree:              0 kB
===FILESYSTEMS===
Filesystem                        1-blocks       Used  Available Capacity Mounted on
overlay                        12000000000 7900000000 3500000000      70% /
proc                                     0          0          0        - /proc
cgroup                                   0          0          0        - /sys/fs/cgroup
/dev/mapper/ubuntu--vg-ubuntu--lv 12000000000 7900000000 3500000000  70% /var/lib/postgresql/data
/dev/mapper/ubuntu--vg-ubuntu--lv 12000000000 7900000000 3500000000  70% /etc/hosts
"""


class HostSnapshotParseTests(unittest.TestCase):
    def test_every_mount_with_capacity_is_kept_and_pseudo_filesystems_skipped(self):
        rows = worker.parse_host_snapshot_output(OUTPUT)
        mounts = [r["mount_point"] for r in rows if r["record_type"] == "STORAGE"]
        self.assertEqual(mounts, ["/", "/var/lib/postgresql/data", "/etc/hosts"])

    def test_data_directory_matches_its_own_mount(self):
        from repository.intelligence import assessment_engine as engine
        rows = [r for r in worker.parse_host_snapshot_output(OUTPUT) if r["record_type"] == "STORAGE"]
        mount = engine.data_mount("/var/lib/postgresql/data", rows)
        self.assertEqual(mount["mount_point"], "/var/lib/postgresql/data")

    def test_report_shows_one_row_per_device(self):
        from repository.report import health_check_report as report
        storage = [dict(r, target_id=7) for r in worker.parse_host_snapshot_output(OUTPUT)
                   if r["record_type"] == "STORAGE"]
        data = report.data_disk({"target_id": 7, "data_directory": "/var/lib/postgresql/data"}, storage)
        shown = report.shown_mounts(storage, {id(data)})
        self.assertEqual([s["mount_point"] for s in shown], ["/", "/var/lib/postgresql/data"])

    def test_older_output_without_disk_sections_leaves_them_unknown(self):
        rows = worker.parse_host_snapshot_output(OUTPUT)
        self.assertIsNone(rows[0]["virtualization"])
        self.assertTrue(all(r["rotational"] is None for r in rows if r["record_type"] == "STORAGE"))

    def test_rotation_per_device_and_hypervisor(self):
        # Cloud container 2026-11-06: virtio disks under KVM report ROTA 1.
        output = OUTPUT + "===BLOCK_DEVICES===\n/dev/mapper/ubuntu--vg-ubuntu--lv    1\n/dev/sdb x\n" \
                          "===VIRTUALIZATION===\nkvm\n"
        rows = worker.parse_host_snapshot_output(output)
        self.assertEqual(rows[0]["virtualization"], "kvm")
        rotation = {r["mount_point"]: r["rotational"] for r in rows if r["record_type"] == "STORAGE"}
        self.assertEqual(rotation, {"/": None, "/var/lib/postgresql/data": True, "/etc/hosts": True})


class DiskTypeNoteTests(unittest.TestCase):
    """The report's note when the data disk reports another type than the profile."""

    def note(self, profile, rotational, virtualization=None, lang="tr"):
        from repository.report import health_check_report as report
        nodes = [{"target_id": 1, "name": "node-1", "data_directory": "/data", "virtualization": virtualization}]
        storage = [{"target_id": 1, "mount_point": "/data", "total_bytes": 10, "rotational": rotational}]
        return report.config_disk_note({"nodes": nodes, "storage": storage}, report.TEXTS[lang], profile)

    def test_no_note_when_the_disk_agrees_or_is_unknown(self):
        self.assertEqual(self.note({"storage_type": {"value": "SSD", "assumed": True}}, False), "")
        self.assertEqual(self.note({"storage_type": {"value": "SSD", "assumed": True}}, None), "")
        self.assertEqual(self.note({}, True), "")                            # older checks: no profile

    def test_assumed_profile_asks_for_the_storage_type(self):
        self.assertEqual(self.note({"storage_type": {"value": "SSD", "assumed": True}}, True),
                         "Disk tipi girilmedi, SSD varsayıldı; veri diski node-1 sunucusunda HDD bildiriyor. "
                         "Doğruysa profilde disk tipini belirtin.")

    def test_given_profile_states_the_conflict_and_a_virtual_disk_caveat(self):
        self.assertEqual(self.note({"storage_type": {"value": "SSD"}}, True, "vmware", "en"),
                         "The profile says SSD; the data disk reports HDD on node-1. On a virtual machine "
                         "(vmware) a disk can appear rotating even when SSD is underneath.")
        self.assertNotIn("virtual", self.note({"storage_type": {"value": "SSD"}}, True, "none", "en"))
        self.assertNotIn("virtual", self.note({"storage_type": {"value": "HDD"}}, False, "kvm", "en"))


if __name__ == "__main__":
    unittest.main()
