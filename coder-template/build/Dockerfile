# Contract analysis workspace image. Everything a workspace needs at runtime
# is baked in here, because workspaces run on an internal network with no
# route to the outside world. Build-time downloads happen outside the enclave.
FROM ubuntu:24.04@sha256:33ceb71981b602c1a7443a53469e4dba065f7503eab3078a2d7a57a2ab987517

ARG CODE_SERVER_VERSION=4.133.0
ARG UV_VERSION=0.12.5
ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-venv curl ca-certificates git socat \
    && rm -rf /var/lib/apt/lists/* \
    && if getent passwd ubuntu >/dev/null; then userdel -r ubuntu; fi \
    && useradd --create-home --shell /bin/bash coder

# code-server, pre-installed so the Coder module runs it in offline mode.
RUN curl -fsSL https://code-server.dev/install.sh \
      | sh -s -- --method=standalone --prefix=/opt/code-server --version="$CODE_SERVER_VERSION" \
    && /opt/code-server/bin/code-server --version | grep -q "^${CODE_SERVER_VERSION} " \
    && chown -R coder:coder /opt/code-server

# uv outside the home volume so it survives volume reuse.
RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
      | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh \
    && test "$(uv --version | awk '{print $2}')" = "$UV_VERSION"

# Python deps from the pinned lockfile (copied in by scripts/dev-up.sh).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/bin/python3 \
    UV_PYTHON_DOWNLOADS=never \
    PYTHONDONTWRITEBYTECODE=1
COPY pyproject.toml uv.lock /opt/pipeline-lock/
RUN cd /opt/pipeline-lock && uv sync --frozen && uv cache clean \
    && chown -R coder:coder /opt/venv

USER coder
WORKDIR /home/coder
