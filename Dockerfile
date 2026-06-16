FROM python:3.13-slim

ARG TARGETARCH=amd64
ARG HELM_VERSION=v4.2.1
ARG KUBECTL_VERSION=v1.36.2

ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /usr/local/bin/

RUN apt-get update \
    && apt-get dist-upgrade -y \
    && apt-get install -y --no-install-recommends ca-certificates curl gzip tar \
    && curl -fsSLo /tmp/helm.tar.gz "https://get.helm.sh/helm-${HELM_VERSION}-linux-${TARGETARCH}.tar.gz" \
    && tar -xzf /tmp/helm.tar.gz -C /tmp \
    && mv "/tmp/linux-${TARGETARCH}/helm" /usr/local/bin/helm \
    && curl -fsSLo /usr/local/bin/kubectl "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${TARGETARCH}/kubectl" \
    && chmod +x /usr/local/bin/helm /usr/local/bin/kubectl \
    && rm -rf /var/lib/apt/lists/* /tmp/helm.tar.gz "/tmp/linux-${TARGETARCH}"

COPY pyproject.toml uv.lock README.md ./
COPY moira_cli ./moira_cli

RUN uv sync --frozen --no-dev

ENTRYPOINT ["moira"]
CMD ["--help"]
