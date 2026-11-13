"""keystone_collect.ps1: finding psql.exe on customer machines, and the package stamp.

The first pilot (2026-11-10) failed on psql: PostgreSQL in E:\\post_data\\bin, a folder typed where a
file was expected, then an old package run by mistake. These cases stay tested. The script is
dot-sourced in PowerShell (pwsh), its functions only; Windows-only cmdlets (Get-Process,
Get-CimInstance, Read-Host) are replaced by functions of the same name, which PowerShell prefers.

Run from the repository root:
    python -B -m unittest discover -s tests -p test_collect_windows.py -v
"""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from repository.offline import bundle

SCRIPT = Path(bundle.OFFLINE_DIR) / "keystone_collect.ps1"
PWSH = shutil.which("pwsh")


def quote(text):
    return "'" + str(text).replace("'", "''") + "'"


@unittest.skipUnless(PWSH, "PowerShell (pwsh) is not installed")
class FindPsqlTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="find_psql_"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.program_files = self.root / "Program Files"

    def psql(self, *parts):
        """A psql.exe at this place under the test root."""
        path = self.root.joinpath(*parts, "psql.exe")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        path.chmod(0o755)
        return path

    def find(self, processes=(), services=(), services_fail=False, answers=(), path_dirs=()):
        """Find-Psql's answer, with the machine described by the arguments."""
        mocks = [
            f"$env:ProgramFiles = {quote(self.program_files)}",
            f"${{env:ProgramFiles(x86)}} = {quote(self.root / 'Program Files (x86)')}",
            f"$env:LOCALAPPDATA = {quote(self.root / 'AppData')}",
            f"$env:PATH = {quote(':'.join(map(str, path_dirs)) or str(self.root / 'empty'))}",
            f". {quote(SCRIPT)}",
            "function Get-Process { param($Name, $ErrorAction) "
            + "".join(f"[pscustomobject]@{{ Path = {quote(p)} }}; " for p in processes) + "}",
            ("function Get-CimInstance { param($ClassName, $ErrorAction) throw 'Access is denied' }"
             if services_fail else
             "function Get-CimInstance { param($ClassName, $ErrorAction) "
             + "".join(f"[pscustomobject]@{{ PathName = {quote(s)} }}; " for s in services) + "}"),
            "$script:answers = [System.Collections.Queue]::new()",
            *[f"$script:answers.Enqueue({quote(a)})" for a in answers],
            "function Read-Host { param($Prompt) if ($script:answers.Count) { $script:answers.Dequeue() } else { '' } }",
            "function Write-Warning { param($Message) }",
            "$found = Find-Psql",
            "if ($found) { Write-Output \"FOUND=$found\" } else { Write-Output 'FOUND=' }",
        ]
        result = subprocess.run([PWSH, "-NoProfile", "-NonInteractive", "-Command", "\n".join(mocks)],
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        line = [l for l in result.stdout.splitlines() if l.startswith("FOUND=")]
        self.assertEqual(len(line), 1, result.stdout + result.stderr)
        value = line[0][len("FOUND="):]
        return Path(value) if value else None

    def test_on_path(self):
        psql = self.psql("bin-on-path")
        self.assertEqual(self.find(path_dirs=[psql.parent]), psql)

    def test_running_server_in_a_non_standard_folder(self):
        """The pilot: PostgreSQL in E:\\post_data\\bin, nothing on PATH."""
        psql = self.psql("post_data", "bin")
        self.assertEqual(self.find(processes=[psql.parent / "postgres.exe"]), psql)

    def test_service_path_when_the_server_is_not_visible(self):
        psql = self.psql("pgsql", "bin")
        service = f'"{psql.parent / "pg_ctl.exe"}" runservice -N "postgresql-x64-14" -D "E:\\data"'
        self.assertEqual(self.find(services=[service]), psql)

    def test_service_query_refused_goes_on_to_standard_folders(self):
        psql = self.psql("Program Files", "PostgreSQL", "16", "bin")
        self.assertEqual(self.find(services_fail=True), psql)

    def test_newest_postgresql_before_older_and_pgadmin(self):
        self.psql("Program Files", "PostgreSQL", "9.6", "bin")
        newest = self.psql("Program Files", "PostgreSQL", "16", "bin")
        self.psql("Program Files", "PostgreSQL", "14", "bin")
        self.psql("Program Files", "pgAdmin 4", "runtime")
        self.assertEqual(self.find(), newest)

    def test_pgadmin_when_no_postgresql(self):
        psql = self.psql("Program Files", "pgAdmin 4", "runtime")
        self.assertEqual(self.find(), psql)

    def test_asked_folder_or_file_with_or_without_quotes(self):
        """The pilot: a folder typed where a file was expected."""
        psql = self.psql("custom", "PostgreSQL 14", "bin")
        for answer in (str(psql.parent), f'"{psql.parent}"', str(psql), f'  "{psql}"  '):
            self.assertEqual(self.find(answers=[answer]), psql, answer)

    def test_asks_three_times_then_gives_up(self):
        psql = self.psql("later", "bin")
        self.assertEqual(self.find(answers=["C:\\nowhere", "", str(psql)]), psql)
        self.assertIsNone(self.find(answers=["a", "b", "c", str(psql)]))


class PackageStampTests(unittest.TestCase):

    def test_generated_scripts_carry_the_package_time(self):
        with tempfile.TemporaryDirectory() as out:
            bundle.write_bundle(out)
            node = (Path(out) / "keystone_node.sql").read_text(encoding="utf-8")
            generated = node.split("generated ", 1)[1].split(")", 1)[0]
            for name in bundle.COLLECT_SCRIPTS:
                text = (Path(out) / name).read_text(encoding="utf-8")
                self.assertNotIn("__KEYSTONE_PACKAGE__", text, name)
                self.assertIn(f'"{generated}"', text, name)

    def test_sources_say_they_are_not_a_package(self):
        for name in bundle.COLLECT_SCRIPTS:
            text = (Path(bundle.OFFLINE_DIR) / name).read_text(encoding="utf-8")
            self.assertEqual(text.count("__KEYSTONE_PACKAGE__"), 1, name)
            self.assertIn("gelistirme kopyasi", text, name)


if __name__ == "__main__":
    unittest.main()
