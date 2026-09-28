"""Scanner command doubles only; never invoke Docker or download executables."""

from contextlib import redirect_stdout
import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch
import urllib.error
import zipfile


spec = importlib.util.spec_from_file_location("scanner", Path(__file__).parents[1] / "scan_images.py")
scanner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scanner)


class ScannerTests(unittest.TestCase):
    def setUp(self):
        for patcher in (
            patch.object(scanner.sys, "argv", ["scan_images.py", "test-only:image"]),
            patch.dict(scanner.os.environ, {"GITHUB_STEP_SUMMARY": ""}),
            patch.object(scanner.platform, "system", return_value="Windows"),
            patch.object(scanner.platform, "machine", return_value="AMD64"),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_missing_image_is_not_suppressed(self):
        with patch.object(scanner.subprocess, "run", side_effect=subprocess.CalledProcessError(1, "docker")):
            with self.assertRaises(subprocess.CalledProcessError):
                scanner.main()

    def test_download_outage_is_explicit_unavailable(self):
        output = io.StringIO()
        with patch.object(scanner.subprocess, "run"), patch.object(scanner.urllib.request, "urlopen", side_effect=urllib.error.URLError("test only")), redirect_stdout(output):
            scanner.main()
        self.assertIn("::warning::", output.getvalue())
        self.assertIn("no security result", output.getvalue())

    def test_checksum_mismatch_never_executes(self):
        with patch.object(scanner.subprocess, "run") as run, patch.object(scanner.urllib.request, "urlopen", return_value=io.BytesIO(b"test-only-invalid-archive")):
            with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
                scanner.main()
        self.assertEqual(run.call_count, 1)  # Only docker image inspect.

    def test_scan_results_are_distinct(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as bundle:
            bundle.writestr("trivy.exe", b"test fixture, never executed")
        data = archive.getvalue()
        for code, message in [(0, "scan completed"), (2, "advisory review required"), (1, "not a clean scan")]:
            with self.subTest(code=code):
                output = io.StringIO()
                with patch.dict(scanner.ASSETS, {"Windows": ("windows-64bit.zip", hashlib.sha256(data).hexdigest())}), patch.object(scanner.urllib.request, "urlopen", return_value=io.BytesIO(data)), patch.object(scanner.subprocess, "run", return_value=subprocess.CompletedProcess([], code)), redirect_stdout(output):
                    scanner.main()
                self.assertIn(message, output.getvalue())


if __name__ == "__main__":
    unittest.main()
