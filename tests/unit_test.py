from dataclasses import dataclass

import pytest

from main import build_metric_value_path, scaling_is_needed


@pytest.mark.parametrize(
    "current_replicas, needed_replicas, return_value",
    [
        (0, 1, True),
        (50, 0, True),
        (0, 0, False),
        (1, 1, False),
        (5, 1, False),
    ],
)
def test_scaling_is_needed(current_replicas, needed_replicas, return_value):
    assert scaling_is_needed(current_replicas=current_replicas, needed_replicas=needed_replicas) == return_value


@dataclass(kw_only=True)
class _Metadata:
    namespace: str
    annotations: dict


@dataclass(kw_only=True)
class _HorizontalPodAutoscaler:
    metadata: _Metadata


@pytest.mark.parametrize(
    "hpa, return_value, exception",
    [
        # Expected config
        (
            _HorizontalPodAutoscaler(
                metadata=_Metadata(
                    namespace="namespace-foo",
                    annotations={
                        "autoscaling.alpha.kubernetes.io/metrics": '[{"type":"Object","object":\
                        {"target":{"kind":"Service","name":"foo-service"},"metricName":\
                        "foo_metric","targetValue":"15k"}}]'
                    },
                )
            ),
            "apis/custom.metrics.k8s.io/v1beta1/namespaces/namespace-foo/services/foo-service/foo_metric",
            None,
        ),
        # Described object is not a service
        (
            _HorizontalPodAutoscaler(
                metadata=_Metadata(
                    namespace="namespace-foo",
                    annotations={
                        "autoscaling.alpha.kubernetes.io/metrics": '[{"type":"Object","object":\
                        {"target":{"kind":"Bar","name":"foo-bar"},"metricName":\
                        "foo_metric","targetValue":"15k"}}]'
                    },
                )
            ),
            None,
            AssertionError,
        ),
        # Service with a selector
        (
            _HorizontalPodAutoscaler(
                metadata=_Metadata(
                    namespace="namespace-foo",
                    annotations={
                        "autoscaling.alpha.kubernetes.io/metrics": '[{"type":"Object","object":\
                        {"target":{"kind":"Service","name":"metrics-generator","apiVersion":\
                        "/v1"},"metricName":"foo_metric","targetValue":"1","selector":\
                        {"matchLabels":{"foo":"foo"}}}}]'
                    },
                )
            ),
            None,
            AssertionError,
        ),
        # Not using a Custom metric
        (
            _HorizontalPodAutoscaler(
                metadata=_Metadata(
                    namespace="namespace-foo",
                    annotations={
                        "autoscaling.alpha.kubernetes.io/metrics": '[{"type":"External","external":\
                        {"metricName":"bar_metric","metricSelector":{"matchLabels":\
                        {"foo": "bar"}},"targetAverageValue":"1"}}]'
                    },
                )
            ),
            None,
            StopIteration,
        ),
    ],
)
def test_build_metric_value_path(hpa, return_value, exception):
    if exception is None:
        assert build_metric_value_path(hpa) == return_value
    else:
        with pytest.raises(exception):
            build_metric_value_path(hpa)
