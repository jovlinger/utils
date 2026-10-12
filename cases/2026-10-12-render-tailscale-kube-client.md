# CASE: Render Tailscale boot dies on kube service account

- Date: 2026-10-12
- Hosts / gear: Render free web service `tailscale-exit`, image `tailscale/tailscale:latest` via `render_exit/render`
- Status: remediated

## 1. Symptoms

The Render deploy builds, then the container exits 1 during "Deploying...". The log line is `boot: ... error initializing kube client: error creating kube client: open /var/run/secrets/kubernetes.io/serviceaccount/namespace: no such file or directory`.

## 2. Evidences

`containerboot` creates a Kubernetes client only when `KubeSecret` is non-empty. If `KUBERNETES_SERVICE_HOST` is set and `TS_KUBE_SECRET` is unset, that value defaults to `tailscale`. The Dockerfile did not set `TS_KUBE_SECRET`. The missing path is the in-cluster service-account mount, which Render does not provide.

Anti-evidence: this is not a missing Dockerfile or a failed image push. The log shows the image layers pushed and the process reached `containerboot` (`boot:`).

## 3. Analysis

`tailscale/tailscale` starts through `containerboot`. That program treats a set `KUBERNETES_SERVICE_HOST` as "running in Kubernetes" and then looks for a Secret named `tailscale` using the pod service account. Render's runtime exports `KUBERNETES_SERVICE_HOST` into the container and does not mount `/var/run/secrets/kubernetes.io/serviceaccount`. `containerboot` exits before `tailscaled` listens.

An explicit empty `TS_KUBE_SECRET` disables Secret storage. Clearing `KUBERNETES_SERVICE_HOST` makes `containerboot` take the non-Kubernetes path and keep state in `TS_STATE_DIR`.

## 4. Remediation

In `render_exit/render/entrypoint.sh`, before `exec containerboot`, set `KUBERNETES_SERVICE_HOST` and `TS_KUBE_SECRET` to empty. The Dockerfile also sets `TS_KUBE_SECRET` empty. The entrypoint assignment is the one that wins, because Render injects `KUBERNETES_SERVICE_HOST` at runtime, after image `ENV`.

Push the utils commit, then `render_exit_util up --deploy`. A push alone does not rebuild.

## Discussion

The same boot line shows up on Azure Container Apps, which also exports `KUBERNETES_SERVICE_HOST` without a usable service-account mount. Blanking only `TS_KUBE_SECRET` is enough to skip the client. Blanking `KUBERNETES_SERVICE_HOST` as well avoids the other Kubernetes-only branches in `containerboot`.
