import json
import logging
import subprocess
from pathlib import Path

import pytest

from main import SYNC_INTERVAL

TESTS_PATH = Path(__file__).parent
MANIFESTS_PATH = TESTS_PATH / "manifests"

TIMEOUT = SYNC_INTERVAL * 3

logger = logging.getLogger(__name__)


def run(*, command: list[str], **kw_args) -> str:
    try:
        return subprocess.check_output(command, timeout=300, text=True, stderr=subprocess.PIPE, **kw_args)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        logger.exception(f"Running the command failed: {e.stderr}")
        raise e


@pytest.fixture(scope="session")
def setup():
    try:
        run(
            command=[
                "helm",
                "repo",
                "add",
                "prometheus-community",
                "https://prometheus-community.github.io/helm-charts",
            ]
        )
        run(
            command=[
                "helm",
                "install",
                "prometheus",
                "prometheus-community/prometheus",
                "--values",
                f"{MANIFESTS_PATH}/prometheus-values.yaml",
                "--wait",
            ]
        )
        run(
            command=[
                "helm",
                "install",
                "prometheus-adapter",
                "prometheus-community/prometheus-adapter",
                "--values",
                f"{MANIFESTS_PATH}/prometheus-adapter-values.yaml",
                "--wait",
            ]
        )

        run(command=["kubectl", "apply", "-f", f"{MANIFESTS_PATH}/metrics-generator.yaml", "--wait=true"])
        yield
    finally:
        run(command=["helm", "delete", "prometheus", "--wait"])
        run(command=["helm", "delete", "prometheus-adapter", "--wait"])
        run(command=["kubectl", "delete", "-f", f"{MANIFESTS_PATH}/metrics-generator.yaml", "--wait=true"])


def deploy_target(manifest: str):
    run(command=["kubectl", "apply", "-f", f"{MANIFESTS_PATH}/{manifest}", "--wait=true"])


def delete_target(manifest: str):
    run(command=["kubectl", "delete", "-f", f"{MANIFESTS_PATH}/{manifest}", "--wait=true"])


def run_scaler():
    return subprocess.Popen(["python", f"{TESTS_PATH.parent}/main.py"])


def set_foo_metric_value(value: int):
    run(
        command=[
            "kubectl",
            "patch",
            "deployment",
            "metrics-generator",
            "-p",
            json.dumps({"spec": {"template": {"metadata": {"labels": {"foo_metric_value": str(value)}}}}}),
        ]
    )
    run(command=["kubectl", "rollout", "status", "deployment", "metrics-generator"])


def wait_scale(*, kind: str, name: str, replicas: int):
    run(
        command=[
            "kubectl",
            "wait",
            f"--for=jsonpath={{.spec.replicas}}={replicas}",
            kind,
            name,
            f"--timeout={TIMEOUT}s",
        ]
    )


@pytest.mark.parametrize("target_name, kind", [("target-1", "deployment"), ("target-2", "statefulset")])
def test_target(setup, target_name: str, kind: str):
    set_foo_metric_value(0)

    deploy_target(f"{target_name}.yaml")

    # The intial replicas count is 1
    wait_scale(kind=kind, name=target_name, replicas=1)

    khstz = run_scaler()

    try:
        # The initial metric value is 0, it should scale the target to 0
        wait_scale(kind=kind, name=target_name, replicas=0)

        # Increase the metric value
        set_foo_metric_value(10)

        # The deloyment was revived anf the HPA was able to scale it up
        wait_scale(kind=kind, name=target_name, replicas=3)
    finally:
        khstz.kill()
        delete_target(f"{target_name}.yaml")
