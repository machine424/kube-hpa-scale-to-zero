# kube-hpa-scale-to-zero

Simulate the [HPAScaleToZero](https://kubernetes.io/docs/reference/command-line-tools-reference/feature-gates/) feature gate, especially for managed Kubernetes clusters,
as they don't usually support non-stable feature gates.

`kube-hpa-scale-to-zero` scales down to `zero` workloads instrumented by HPA when the current
value of the used _custom_ metric is `zero` and resuscitates them when needed.

![how](./how.png)

If you're also tired of (big) Pods (thus Nodes) that are only used 3 hours a day, give this a try ;)

Check the code and comments in [main.py](./main.py) for more details.

### Run

`python main.py --hpa-label-selector foo=bar,bar=foo --hpa-namespace foo`

or

`python main.py --help`

Needs Python `>=3.10`

### Deploy

Docker images are published [here](https://hub.docker.com/r/machine424/kube-hpa-scale-to-zero).

A Helm chart is also available [here](./helm-chart).

`helm upgrade --install RELEASE_NAME helm-chart/ -n RELEASE_NAMESPACE`
