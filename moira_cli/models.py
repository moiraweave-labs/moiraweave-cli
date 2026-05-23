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


class CatalogSourceConfig(BaseModel):
    """Official step catalog source.

    :param name: Catalog name (e.g., "moiraweave-official").
    :param uri: Git or registry URI for the catalog.
    :param version_constraint: Optional semver constraint (e.g., "^1.0.0").
    :param enabled: Whether this catalog is enabled for step discovery.
    """

    name: str
    uri: str = "https://github.com/moiraweave-labs/moiraweave-steps"
    version_constraint: str = "*"
    enabled: bool = True


class MoiraWeaveConfig(BaseModel):
    """Root moiraweave.yaml model.

    :param name: Project name.
    :param registry: OCI registry used for images.
    :param environments: Named environment configurations.
    :param workloads_dir: Directory containing workload manifests.
    :param artifacts_dir: Directory containing local artifacts.
    :param catalogs: Named official step catalogs (e.g., moiraweave-official).
    :param runtime_version: Pinned runtime version for compatibility checks.
    """

    name: str
    registry: str
    environments: dict[str, EnvironmentConfig] = Field(default_factory=dict)
    catalogs: dict[str, CatalogSourceConfig] = Field(default_factory=dict)
    workloads_dir: str = ".moiraweave/workloads"
    artifacts_dir: str = ".moiraweave/artifacts"
    deploy_dir: str = ".moiraweave/deploy"
    pipelines_dir: str = ".moiraweave/pipelines"
    steps_dir: str = ".moiraweave/steps"
    tasks_dir: str = ".moiraweave/tasks"
    runtime_version: str = "0.1.0"
