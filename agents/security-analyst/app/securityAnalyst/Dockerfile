# Base images come from AWS ECR Public (a mirror of the official Docker Library
# images) rather than Docker Hub: anonymous Docker Hub pulls from CodeBuild's
# shared IP ranges routinely hit "429 Too Many Requests", which fails the
# container build and rolls back the whole stack (sibling agent's issue #77).
#
# This story (S-125) scaffolds the deployable no-op: no scanner toolchains
# (semgrep/gitleaks/trivy/checkov/CodeQL) are installed yet — S-126+ extends
# this Dockerfile per spec S15.2 once the scan step is implemented. git + gh
# CLI are enough for this story's checkout step.

FROM public.ecr.aws/docker/library/python:3.13-slim AS base

# Custom CA certificates (e.g. corporate proxy like Netskope)
# Pass at build time: --build-arg EXTRA_CA_CERT=path/to/cert.pem
# Without the arg, an empty placeholder is copied and skipped.
ARG EXTRA_CA_CERT=.ca-placeholder
COPY ${EXTRA_CA_CERT} /usr/local/share/ca-certificates/extra-ca.crt
RUN if [ -s /usr/local/share/ca-certificates/extra-ca.crt ]; then \
      update-ca-certificates; \
    fi

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg && \
    rm -rf /var/lib/apt/lists/*

# gh CLI (from Debian repos as fallback when GitHub apt has SSL issues)
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
    | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
    https://cli.github.com/packages stable main" \
    > /etc/apt/sources.list.d/github-cli.list && \
    apt-get update && apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Python deps
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code
COPY . .

EXPOSE 8080
CMD ["python", "main.py"]
