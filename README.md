## Usage

[Helm](https://helm.sh) must be installed to use the charts.  Please refer to
Helm's [documentation](https://helm.sh/docs) to get started.

Once Helm has been set up correctly, add the repo as follows:

    helm repo add kube-hpa-scale-to-zero https://machine424.github.io/kube-hpa-scale-to-zero

If you had already added this repo earlier, run `helm repo update` to retrieve
the latest versions of the packages.  You can then run `helm search repo
kube-hpa-scale-to-zero` to see the charts.

To install the kube-hpa-scale-to-zero chart:

    helm install RELEASE_NAME kube-hpa-scale-to-zero/kube-hpa-scale-to-zero -n RELEASE_NAMESPACE

To uninstall the chart:

    helm delete RELEASE_NAME -n RELEASE_NAMESPACE