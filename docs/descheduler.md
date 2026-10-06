# Optional AKS descheduler

The cloud janitor and Kubernetes descheduler solve different problems. The janitor stops explicitly expired Azure resources. The descheduler evicts selected pods so the scheduler can place them again according to current affinity and taints. Eviction is disruptive and does not by itself save money, resize a node pool, or safely drain a pool before its Azure stop.

`deploy/descheduler-values.yaml` targets the official `kubernetes-sigs/descheduler` chart **0.34.0**. Check the upstream Kubernetes compatibility matrix against your AKS version before installation. Install with a cluster administrator's Kubernetes identity; the cloud janitor has no kubeconfig or cluster-admin credentials.

```sh
helm repo add descheduler https://kubernetes-sigs.github.io/descheduler/
helm template ephemeral-descheduler descheduler/descheduler \
  --version 0.34.0 --namespace kube-system \
  --values deploy/descheduler-values.yaml > /tmp/descheduler.yaml
# Review the rendered ClusterRole, CronJob and policy before installing.
helm upgrade --install ephemeral-descheduler descheduler/descheduler \
  --version 0.34.0 --namespace kube-system \
  --values deploy/descheduler-values.yaml
```

The supplied policy is dry-run. It selects Kubernetes pods labeled `janitor-managed=true`, excludes system namespaces, uses `nodeFit`, protects PVC-bearing pods and pods without PDBs, requires at least two replicas and one-hour pod age, and limits evictions to one per node, two per namespace, and three total per run. Only node-affinity and node-taint violations are enabled. The CronJob forbids overlapping executions and has a three-minute deadline.

Azure pool tags and Kubernetes pod labels are separate enrollment systems. Labeling a pod does not enroll its pool; enrolling a pool does not give its pods eviction consent. Before turning off `cmdOptions.dry-run`, inspect candidates, PDBs, spare capacity, anti-affinity and application recovery. The eviction API and descheduler safeguards reduce disruption but cannot guarantee application availability.

Do not treat this chart as an automated pre-stop gate. If you need proof of drain completion, build an explicit Kubernetes eviction/drain workflow and make successful completion a prerequisite for the Azure lifecycle action. That integration is outside this release.
