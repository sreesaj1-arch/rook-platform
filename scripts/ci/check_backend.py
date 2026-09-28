"""Repository syntax and API contracts; no clients, databases or telemetry started."""

import ast
import json
import os
from pathlib import Path
import subprocess
import tomllib

from rook_backend.api.app import create_app


ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
files = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
).decode().split("\0")
for name in filter(None, files):
    path = ROOT / name
    if not path.is_file():
        continue
    if path.suffix == ".py":
        ast.parse(path.read_text(encoding="utf-8"), filename=name)
    elif path.suffix == ".toml":
        tomllib.loads(path.read_text(encoding="utf-8"))

schema = create_app().openapi()
json.dumps(schema, allow_nan=False)
assert schema["openapi"].startswith("3.")
for route in ("/health/live", "/health/ready", "/services/{service_name}/metrics", "/incidents", "/incidents/{incident_id}"):
    assert "get" in schema["paths"][route], route

subprocess.run(["git", "diff", "--check"], check=True)
base = os.environ.get("DIFF_BASE", "")
if base and set(base) != {"0"}:
    subprocess.run(["git", "diff", "--check", f"{base}...HEAD"], check=True)
elif os.environ.get("GITHUB_ACTIONS") == "true":
    subprocess.run(["git", "show", "--format=", "--check", "HEAD"], check=True)
# git diff does not inspect untracked files in a local working tree.
new_files = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard", "-z"]).decode().split("\0")
for name in filter(None, new_files):
    path = ROOT / name
    if path.suffix in {".py", ".ps1", ".md", ".yaml", ".yml", ".toml", ".json", ".txt"}:
        text = path.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            assert line == line.rstrip(), f"{name}:{number}: trailing whitespace"
print("Python syntax, TOML, OpenAPI and changed-file whitespace passed")
