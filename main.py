import argparse
import json
import logging
import threading
from dataclasses import dataclass
from time import sleep

import kubernetes
import kubernetes.dynamic.exceptions
from kubernetes import watch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)8s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
LOGGER = logging.getLogger(__name__)


def load_kubernetes_config() -> None:
    try:
        kubernetes.config.load_incluster_config()
    except kubernetes.config.ConfigException:
        kubernetes.config.load_kube_config()


load_kubernetes_config()
AUTOSCALING_V1 = kubernetes.client.AutoscalingV1Api()
DYNAMIC = kubernetes.dynamic.DynamicClient(kubernetes.client.api_client.ApiClient())
CLIENTS = {}


@dataclass(slots=True, kw_only=True)
class HPA:
    name: str
    namespace: str
    metric_value_path: str
    target_kind: str
    target_name: str


SYNC_INTERVAL = 30
HPAs: dict[str, HPA] = {}
_LOCK = threading.Lock()


def watch_metrics() -> None:
    """
    periodically watches metrics of HPA in HPAs and scale the targets accordingly if needed.
    """
    # TODO: See if we can use Kube's watch
    def _watch():
        while True:
            for hpa in list(HPAs.values()):
                update_target(hpa)

            sleep(SYNC_INTERVAL)

    threading.Thread(target=_watch, daemon=True).start()


def watch_hpa(args) -> None:
    LOGGER.info(
        f"Will watch HPA with label selector '{args.hpa_label_selector}' in {args.hpa_namespace}."
    )
    while True:
        try:
            w = watch.Watch()
            for event in w.stream(
                AUTOSCALING_V1.list_namespaced_horizontal_pod_autoscaler,
                args.hpa_namespace,
                label_selector=args.hpa_label_selector,
            ):
                update_hpa(event["object"].metadata)
        except kubernetes.client.exceptions.ApiException as exc:
            if exc.status != 410:
                raise exc


def update_hpa(metadata) -> None:
    """
    inserts/updates/deletes the HPA to/in/from HPAs.
    """
    hpa_namespace, hpa_name = metadata.namespace, metadata.name
    namespaced_name = f"{hpa_namespace}/{hpa_name}"
    try:
        hpa = AUTOSCALING_V1.read_namespaced_horizontal_pod_autoscaler(
            namespace=hpa_namespace, name=hpa_name
        )
        hpa = HPA(
            name=hpa_name,
            namespace=hpa_namespace,
            metric_value_path=build_metric_value_path(hpa),
            target_kind=hpa.spec.scale_target_ref.kind,
            target_name=hpa.spec.scale_target_ref.name,
        )
        with _LOCK:
            HPAs[namespaced_name] = hpa
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            LOGGER.info(f"HPA {hpa_namespace}/{hpa_name} was not found.")
            with _LOCK:
                HPAs.pop(namespaced_name, None)
            return
        raise exc


def build_metric_value_path(hpa) -> str:
    """
    returns the Kube API path to retrieve the custom.metrics.k8s.io used metric.
    """
    metrics = json.loads(
        hpa.metadata.annotations["autoscaling.alpha.kubernetes.io/metrics"]
    )
    # Only supports ONE CUSTOM metric without selector based on service for now.
    custom_metric = next(m["object"] for m in metrics if m["type"] == "Object")
    target = custom_metric["target"]
    assert target["kind"] == "Service"
    assert not target.get("selector")

    service_namespace = hpa.metadata.namespace
    service_name = target["name"]
    metric_name = custom_metric["metricName"]

    return f"apis/custom.metrics.k8s.io/v1beta1/namespaces/{service_namespace}/services/{service_name}/{metric_name}"


def get_needed_replicas(metric_value_path) -> int | None:
    """
    returns 0 if the metric value is 0, and 1 otherwise (HPA will take care of scaling up if needed)
    returns None, if the needed replicas cannot be determined.
    """
    try:
        metric_value = DYNAMIC.request("GET", metric_value_path).items[0].value
        return min(int(metric_value), 1)
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            LOGGER.info(f"Custom metric at {metric_value_path} was not found.")
            return
        raise exc
    except (
        kubernetes.dynamic.exceptions.ServiceUnavailableError,
        kubernetes.dynamic.exceptions.UnauthorizedError,
    ) as exc:
        LOGGER.exception(f"An exception was caught: {exc}")
        return


def update_target(hpa: HPA) -> None:
    needed_replicas = get_needed_replicas(hpa.metric_value_path)
    if needed_replicas is None:
        LOGGER.info(
            f"Will not update {hpa.target_kind} {hpa.namespace}/{hpa.target_name}."
        )
        return
    # Maybe, be more precise (using target_api_version e.g.?)
    match hpa.target_kind:
        case "Deployment":
            scale_deployment(
                namespace=hpa.namespace,
                name=hpa.target_name,
                needed_replicas=needed_replicas,
            )
        case _:
            raise ValueError("Only support Deployment as HPA target for now.")


def update_replicas(*, current_replicas, needed_replicas) -> bool:
    """
    checks if the scale up/down is relevant.
    """
    # Maybe scale to 0 even if needed_replicas == 0, in case
    # Maybe do not scale down if HPA unable to retrieve metrics? leave the current only pod do some work
    if (needed_replicas == current_replicas) or (
        needed_replicas == 1 and current_replicas > 0
    ):
        return False
    return True


def scale_deployment(*, namespace, name, needed_replicas) -> None:
    """
    scales up/down the Deployment if needed.
    """
    app_v1 = CLIENTS.setdefault("app/v1", kubernetes.client.AppsV1Api())
    try:
        scale = app_v1.read_namespaced_deployment_scale(namespace=namespace, name=name)
        current_replicas = scale.status.replicas
        if not update_replicas(
            current_replicas=current_replicas, needed_replicas=needed_replicas
        ):
            LOGGER.info(
                f"No need to scale Deployment {namespace}/{name} {current_replicas}->{needed_replicas}."
            )
            return

        scale.spec.replicas = needed_replicas
        # Maybe do not scale immediately? but don't want to reimplement an HPA.
        app_v1.patch_namespaced_deployment_scale(
            namespace=namespace, name=name, body=scale
        )
        LOGGER.info(
            f"Deployment {namespace}/{name} scaled {current_replicas}->{needed_replicas}."
        )
    except kubernetes.client.exceptions.ApiException as exc:
        if exc.status == 404:
            LOGGER.info(f"Deployment {namespace}/{name} was not found.")
            return
        raise exc


def parse_cli_args():
    parser = argparse.ArgumentParser(
        description="kube-hpa-scale-to-zero. Check https://github.com/machine424/kube-hpa-scale-to-zero"
    )
    parser.add_argument(
        "--hpa-namespace",
        dest="hpa_namespace",
        default="default",
        help="namespace where the HPA live. (default: 'default' namespace)",
    )
    parser.add_argument(
        "--hpa-label-selector",
        dest="hpa_label_selector",
        default="",
        help="label_selector to get HPA to watch, 'foo=bar,bar=foo' e.g. (default: empty string to select all)",
    )

    return parser.parse_args()


if __name__ == "__main__":
    cli_args = parse_cli_args()
    watch_metrics()
    watch_hpa(cli_args)
