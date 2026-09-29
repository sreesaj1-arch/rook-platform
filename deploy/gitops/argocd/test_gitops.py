"""Offline GitOps safety/render contracts; no cluster, credentials or telemetry."""

import copy
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
APP = yaml.safe_load((HERE / "application.yaml").read_text())
PROJECT = yaml.safe_load((HERE / "project.yaml").read_text())
SYNC = yaml.safe_load((HERE / "sync.yaml").read_text())


def validate(application: dict, project: dict, operation: dict) -> None:
    """Fail closed on this local handoff's boundaries, not a general Argo schema."""
    assert application["apiVersion"] == project["apiVersion"] == "argoproj.io/v1alpha1"
    assert application["kind"] == "Application" and project["kind"] == "AppProject"
    assert application["metadata"]["name"] == "rook"
    assert application["metadata"]["namespace"] == project["metadata"]["namespace"] == "argocd"
    assert not application["metadata"].get("finalizers")
    spec = application["spec"]
    assert spec["project"] == project["metadata"]["name"] == "rook-local"
    destination = {"server": "https://kubernetes.default.svc", "namespace": "rook-k8s-local"}
    assert spec["destination"] == destination
    assert project["spec"]["destinations"] == [destination]
    source = spec["source"]
    assert source["repoURL"] == "https://github.com/sreesaj1-arch/rook-platform.git"
    assert project["spec"]["sourceRepos"] == [source["repoURL"]]
    assert re.fullmatch(r"[0-9a-f]{40}", source["targetRevision"])
    assert source["path"] == "deploy/helm/rook"
    assert (ROOT / source["path"] / "Chart.yaml").is_file()
    assert source["helm"]["releaseName"] == application["metadata"]["name"]
    assert not any(key in source["helm"] for key in ("parameters", "values", "valueFiles", "fileParameters"))
    assert spec["syncPolicy"] == {"syncOptions": ["FailOnSharedResource=true"]}
    assert not spec.get("ignoreDifferences")
    assert not project["spec"]["clusterResourceWhitelist"]
    assert {(x["group"], x["kind"]) for x in project["spec"]["namespaceResourceWhitelist"]} == {
        ("apps", "Deployment"), ("apps", "StatefulSet"), ("", "Service"), ("", "ConfigMap")}
    assert operation["operation"]["sync"] == {
        "prune": False, "syncStrategy": {"apply": {"force": False}}}
    values = source["helm"]["valuesObject"]
    assert values["postgres"]["secret"] == {"create": False, "name": "rook-db", "passwordKey": "password"}
    assert values["worker"]["replicas"] == 1
    for name in ("api", "worker", "frontend"):
        assert values[name]["imagePullPolicy"] == "Never"
        assert ":" in values[name]["image"] and not values[name]["image"].endswith(":latest")
    url = urlsplit(values["telemetry"]["prometheusUrl"])
    assert url.scheme in {"http", "https"} and url.hostname
    assert not url.username and not url.password and not url.query


class GitOpsTests(unittest.TestCase):
    def test_local_contract(self):
        validate(APP, PROJECT, SYNC)

    def test_remote_destination_rejected(self):
        app = copy.deepcopy(APP)
        app["spec"]["destination"]["server"] = "https://remote.invalid"
        with self.assertRaises(AssertionError):
            validate(app, PROJECT, SYNC)

    def test_automatic_sync_and_finalizers_rejected(self):
        for change in ("automated", "finalizer", "namespace"):
            app = copy.deepcopy(APP)
            if change == "automated":
                app["spec"]["syncPolicy"]["automated"] = {"prune": True}
            elif change == "finalizer":
                app["metadata"]["finalizers"] = ["resources-finalizer.argocd.argoproj.io"]
            else:
                app["spec"]["syncPolicy"]["syncOptions"].append("CreateNamespace=true")
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate(app, PROJECT, SYNC)

    def test_secret_values_and_url_credentials_rejected(self):
        for change in ("password", "url", "secret-kind"):
            app, project = copy.deepcopy(APP), copy.deepcopy(PROJECT)
            values = app["spec"]["source"]["helm"]["valuesObject"]
            if change == "password":
                values["postgres"]["secret"]["password"] = "test-only-invalid-value"
            elif change == "url":
                values["telemetry"]["prometheusUrl"] = "http://test:fixture@localhost:9090"
            else:
                project["spec"]["namespaceResourceWhitelist"].append({"group": "", "kind": "Secret"})
            with self.subTest(change=change), self.assertRaises(AssertionError):
                validate(app, project, SYNC)

    def test_mutable_revision_and_selector_mismatch_rejected(self):
        for field, value in (("targetRevision", "HEAD"), ("path", "deploy")):
            app = copy.deepcopy(APP)
            app["spec"]["source"][field] = value
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate(app, PROJECT, SYNC)
        app = copy.deepcopy(APP)
        app["spec"]["source"]["helm"]["releaseName"] = "another-release"
        with self.assertRaises(AssertionError):
            validate(app, PROJECT, SYNC)

    def test_prune_or_force_request_rejected(self):
        for field in ("prune", "force"):
            request = copy.deepcopy(SYNC)
            if field == "prune":
                request["operation"]["sync"]["prune"] = True
            else:
                request["operation"]["sync"]["syncStrategy"]["apply"]["force"] = True
            with self.subTest(field=field), self.assertRaises(AssertionError):
                validate(APP, PROJECT, request)

    def test_render_resource_boundaries_and_secret_references(self):
        self.assertIsNotNone(shutil.which("helm"), "Helm required; do not silently skip rendering")
        values = APP["spec"]["source"]["helm"]["valuesObject"]
        result = subprocess.run(
            ["helm", "template", "rook", str(ROOT / "deploy/helm/rook"),
             "--namespace", "rook-k8s-local", "-f", "-"],
            input=yaml.safe_dump(values), text=True, capture_output=True, check=True)
        docs = [d for d in yaml.safe_load_all(result.stdout) if d]
        self.assertTrue(docs)
        for doc in docs:
            self.assertIn(doc["kind"], {"Deployment", "StatefulSet", "Service", "ConfigMap"})
            self.assertTrue(doc["metadata"]["name"].startswith("rook-"))
            self.assertEqual(doc["metadata"].get("namespace", "rook-k8s-local"), "rook-k8s-local")
            if doc["kind"] in {"Deployment", "StatefulSet"}:
                pod = doc["spec"]["template"]["spec"]
                for container in pod["containers"] + pod.get("initContainers", []):
                    for env in container.get("env", []):
                        if "PASSWORD" in env["name"]:
                            self.assertNotIn("value", env)
                            self.assertEqual(env["valueFrom"]["secretKeyRef"], {"name": "rook-db", "key": "password"})
        self.assertNotIn("kind: Secret", result.stdout)
        self.assertNotIn("kind: Namespace", result.stdout)


if __name__ == "__main__":
    unittest.main()
