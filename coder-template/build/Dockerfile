# Contract analysis workspace image. Everything a workspace needs at runtime
# is baked in here, because workspaces run on an internal network with no
# route to the outside world. Build-time downloads happen outside the enclave.
FROM ubuntu:24.04

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       python3 python3-venv curl ca-certificates git sudo \
    && rm -rf /var/lib/apt/lists/* \
    && userdel -r ubuntu 2>/dev/null || true \
    && useradd -m -s /bin/bash coder \
    && echo "coder ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/coder

# code-server, pre-installed so the Coder module runs it in offline mode.
RUN curl -fsSL https://code-server.dev/install.sh \
      | sh -s -- --method=standalone --prefix=/opt/code-server \
    && chown -R coder:coder /opt/code-server

# uv outside the home volume so it survives volume reuse.
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Python deps from the pinned lockfile (copied in by scripts/dev-up.sh).
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_PYTHON=/usr/bin/python3
COPY pyproject.toml uv.lock /opt/pipeline-lock/
RUN cd /opt/pipeline-lock && uv sync --frozen && uv cache clean \
    && chown -R coder:coder /opt/venv

USER coder
WORKDIR /home/coder
