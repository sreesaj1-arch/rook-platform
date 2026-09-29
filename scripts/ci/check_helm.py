"""Fail if Helm is missing; run real renders and existing contracts without a cluster."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
assert shutil.which("helm"), "Helm is required; rendering tests must not silently skip"
subprocess.run(["helm", "version", "--short"], check=True)
files = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]).decode().split("\0")
for name in filter(None, files):
    path = Path(name)
    if path.suffix in {".yml", ".yaml"} and path.is_file() and "deploy/helm/rook/templates/" not in name:
        # Syntax only here: Compose has !override/!reset tags. BaseLoader also
        # preserves the GitHub Actions 'on' key instead of YAML 1.1 booleans.
        list(yaml.load_all(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader))
for overrides in ([], ["--set", "canary.enabled=true", "--set", "apiTraffic=canary"]):
    subprocess.run(["helm", "lint", "deploy/helm/rook", *overrides], check=True)
# Existing tests render default, staged-canary and selected-canary manifests,
# parse their YAML, verify probes/selectors and require unrelated resources unchanged.
subprocess.run([sys.executable, "deploy/helm/rook/tests/test_chart.py"], check=True)
subprocess.run([sys.executable, "deploy/gitops/argocd/test_gitops.py"], check=True)
print("YAML, Helm lint/render and canary contracts passed")
