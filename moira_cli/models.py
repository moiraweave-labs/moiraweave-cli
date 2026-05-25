"""Pydantic models for MoiraWeave project configuration."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EnvironmentConfig(BaseModel):
    """Environment entry from moiraweave.yaml.

    :param context: Runtime context (docker-compose or kubernetes).
    :param values: Optional path to env values file for local context.
    :param kubeconfig: Optional kubeconfig path.
    :param namespace: Optional Kubernetes namespace.
    :param helm_values: Optional Helm values file path.
    :param deploy: Optional deploy strategy.
    :param argocd_app: Optional ArgoCD app name.
    """

    context: str
    values: str | None = None
    kubeconfig: str | None = None
    namespace: str | None = None
    helm_values: str | None = None
    deploy: str | None = None
    argocd_app: str | None = None


class MoiraWeaveConfig(BaseModel):
    """Root moiraweave.yaml model.

    :param name: Project name.
    :param registry: OCI registry used for images.
    :param environments: Named environment configurations.
    :param workloads_dir: Directory containing workload manifests.
    :param artifacts_dir: Directory containing local artifacts.
    :param runtime_version: Pinned runtime version for compatibility checks.
    """

    name: str
    registry: str
    environments: dict[str, EnvironmentConfig] = Field(default_factory=dict)
    workloads_dir: str = ".moiraweave/workloads"
    artifacts_dir: str = ".moiraweave/artifacts"
    deploy_dir: str = ".moiraweave/deploy"
    runtime_version: str = "0.1.0"
