"""Chart contracts; run with Python providing PyYAML/jsonschema and optional Helm."""

import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

import jsonschema
import yaml


CHART = Path(__file__).resolve().parents[1]
VALUES = yaml.safe_load((CHART / "values.yaml").read_text())
SCHEMA = json.loads((CHART / "values.schema.json").read_text())


class ValuesTests(unittest.TestCase):
    def test_default_routes_stable(self):
        jsonschema.validate(VALUES, SCHEMA)
        self.assertEqual(VALUES["apiTraffic"], "stable")
        self.assertFalse(VALUES["canary"]["enabled"])

    def test_enabled_canary_can_receive_traffic(self):
        values = copy.deepcopy(VALUES)
        values["canary"]["enabled"] = True
        values["apiTraffic"] = "canary"
        jsonschema.validate(values, SCHEMA)

    def test_unsafe_values_rejected(self):
        cases = [
            ("apiTraffic", "weighted"),
            ("apiTraffic", "canary"),  # Disabled canary cannot receive traffic.
            ("canary.replicas", 0),
            ("canary.version", "unsafe/version"),
            ("canary.version", ""),
        ]
        for key, value in cases:
            with self.subTest(key=key, value=value):
                values = copy.deepcopy(VALUES)
                target = values
                parts = key.split(".")
                for part in parts[:-1]:
                    target = target[part]
                target[parts[-1]] = value
                with self.assertRaises(jsonschema.ValidationError):
                    jsonschema.validate(values, SCHEMA)

    def test_canary_cannot_remove_stable(self):
        values = copy.deepcopy(VALUES)
        values["canary"]["enabled"] = True
        values["api"]["replicas"] = 0
        with self.assertRaises(jsonschema.ValidationError):
            jsonschema.validate(values, SCHEMA)


@unittest.skipUnless(shutil.which("helm"), "Helm unavailable; rendering unverified")
class RenderTests(unittest.TestCase):
    def render(self, *overrides):
        command = ["helm", "template", "rook", str(CHART)]
        for override in overrides:
            command.extend(["--set", override])
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        return {
            (doc["kind"], doc["metadata"]["name"]): doc
            for doc in yaml.safe_load_all(result.stdout) if doc
        }

    def test_default_does_not_deploy_canary(self):
        docs = self.render()
        self.assertNotIn(("Deployment", "rook-api-canary"), docs)
        self.assertNotIn(("Service", "rook-api-canary"), docs)
        self.assertEqual(docs["Service", "rook-api"]["spec"]["selector"]["app.kubernetes.io/component"], "api")

    def test_canary_probes_and_disjoint_selectors(self):
        docs = self.render("canary.enabled=true")
        stable = docs["Deployment", "rook-api"]
        canary = docs["Deployment", "rook-api-canary"]
        self.assertNotEqual(stable["spec"]["selector"], canary["spec"]["selector"])
        for name in ("rook-api", "rook-api-canary"):
            pod = docs["Deployment", name]["spec"]["template"]["spec"]
            container = pod["containers"][0]
            self.assertEqual(container["securityContext"]["runAsUser"], 10001)
            self.assertEqual(container["readinessProbe"]["httpGet"]["path"], "/health/ready")
            self.assertEqual(container["livenessProbe"]["httpGet"]["path"], "/health/live")
            self.assertIn("startupProbe", container)

    def test_switch_changes_only_active_service(self):
        before = self.render("canary.enabled=true", "apiTraffic=stable")
        after = self.render("canary.enabled=true", "apiTraffic=canary")
        changed = {key for key in before if before[key] != after[key]}
        self.assertEqual(changed, {("Service", "rook-api")})
        self.assertEqual(after["Service", "rook-api"]["spec"]["selector"]["app.kubernetes.io/component"], "api-canary")

    def test_enabling_preserves_other_workloads(self):
        before = self.render()
        after = self.render("canary.enabled=true")
        for key in before:
            self.assertEqual(before[key], after[key], key)


if __name__ == "__main__":
    unittest.main()
