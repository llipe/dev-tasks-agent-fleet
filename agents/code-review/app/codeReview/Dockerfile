# Base image from AWS ECR Public (a mirror of the official Docker Library
# images), as the siblings: anonymous Docker Hub pulls from CodeBuild's shared
# IP ranges hit "429 Too Many Requests" (dependency-update issue #77).
#
# No scanner toolchains, no git, no gh CLI: this agent never clones and never
# shells out (D-07). It reads GitHub over REST (`requests`) and calls Bedrock
# Converse (`boto3`), so the image is Python plus the pinned dependencies only.

FROM public.ecr.aws/docker/library/python:3.13-slim AS base

# Custom CA certificates (e.g. a corporate proxy).
# Pass at build time: --build-arg EXTRA_CA_CERT=path/to/cert.pem
# Without the arg, an empty placeholder is copied and skipped.
ARG EXTRA_CA_CERT=.ca-placeholder
COPY ${EXTRA_CA_CERT} /usr/local/share/ca-certificates/extra-ca.crt
RUN if [ -s /usr/local/share/ca-certificates/extra-ca.crt ]; then \
      update-ca-certificates; \
    fi

# Python deps
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Agent code
COPY . .

EXPOSE 8080
CMD ["python", "main.py"]
