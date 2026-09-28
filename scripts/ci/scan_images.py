"""Advisory local-image scan; no credentials, uploads, application execution or push."""

import hashlib
import os
from pathlib import Path
import platform
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile


VERSION = "0.69.3"
# Digests verified against the official immutable GitHub release asset metadata.
ASSETS = {
    "Linux": ("Linux-64bit.tar.gz", "1816b632dfe529869c740c0913e36bd1629cb7688bd5634f4a858c1d57c88b75"),
    "Windows": ("windows-64bit.zip", "74362dc711383255308230ecbeb587eb1e4e83a8d332be5b0259afac6e0c2224"),
}


def report(message: str, warning: bool = False) -> None:
    print(("::warning::" if warning else "") + message, flush=True)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"- {message}\n")


def main() -> None:
    images = sys.argv[1:]
    if not images:
        raise SystemExit("Usage: scan_images.py IMAGE [IMAGE ...]")
    # Missing build outputs are genuine failures, not scanner availability problems.
    for image in images:
        subprocess.run(["docker", "image", "inspect", image], check=True, stdout=subprocess.DEVNULL)
    system = platform.system()
    if system not in ASSETS or platform.machine().lower() not in {"amd64", "x86_64"}:
        report("Image scan unavailable: this helper supports Linux/Windows x64 only.", True)
        return
    asset, expected = ASSETS[system]
    with tempfile.TemporaryDirectory(prefix="rook-scan-") as directory:
        root = Path(directory)
        archive = root / asset
        url = f"https://github.com/aquasecurity/trivy/releases/download/v{VERSION}/trivy_{VERSION}_{asset}"
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                archive.write_bytes(response.read())
        except (urllib.error.URLError, TimeoutError):
            report("Image scan unavailable: pinned scanner download failed; no security result was produced.", True)
            return
        if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
            raise SystemExit("Scanner checksum mismatch; refusing to execute downloaded binary")
        name = "trivy.exe" if system == "Windows" else "trivy"
        executable = root / name
        if system == "Windows":
            with zipfile.ZipFile(archive) as bundle:
                executable.write_bytes(bundle.read(name))
        else:
            with tarfile.open(archive) as bundle:
                with bundle.extractfile(name) as source:
                    executable.write_bytes(source.read())
            executable.chmod(0o700)
        for image in images:
            command = [str(executable), "image", "--image-src", "docker", "--scanners", "vuln",
                       "--severity", "HIGH,CRITICAL", "--exit-code", "2", "--timeout", "3m",
                       "--cache-dir", str(root / "cache"), image]
            try:
                result = subprocess.run(command, timeout=210)
            except subprocess.TimeoutExpired:
                report(f"{image}: scanner timed out; vulnerability coverage unavailable.", True)
                continue
            if result.returncode == 0:
                report(f"{image}: scan completed; no HIGH/CRITICAL findings reported by this database.")
            elif result.returncode == 2:
                report(f"{image}: HIGH/CRITICAL findings reported above; advisory review required.", True)
            else:
                report(f"{image}: scanner/database unavailable (exit {result.returncode}); not a clean scan.", True)


if __name__ == "__main__":
    main()
