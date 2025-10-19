FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000
ARG KATAGO_VERSION=1.16.3
ARG KATAGO_PACKAGE=katago-v${KATAGO_VERSION}-cuda12.1-cudnn8.9.7-linux-x64.zip
ARG KATAGO_NETWORK_URL=https://media.katagotraining.org/uploaded/networks/models/kata1/kata1-b28c512nbt-s11233360640-d5406293331.bin.gz
ARG KATAGO_NETWORK_BASENAME=kata1-b28c512nbt-s11233360640-d5406293331.bin.gz

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=off
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=100
ENV POETRY_HOME=/opt/poetry
ENV PATH=$POETRY_HOME/bin:/home/${USERNAME}/.local/bin:$PATH
ENV KATAGO_ROOT=/opt/katago

# Install system dependencies and Python runtime
RUN apt-get update && \
  apt-get install -y --no-install-recommends \
  sudo \
  ca-certificates \
  curl \
  wget \
  git \
  unzip \
  build-essential \
  libopenblas-dev \
  libzstd1 \
  libtcmalloc-minimal4 \
  python3 \
  python3-dev \
  python3-venv \
  python3-pip \
  python-is-python3 \
  gnugo \
  && rm -rf /var/lib/apt/lists/*

ENV PATH="/usr/games:${PATH}"

# Create non-root user for VS Code and devcontainers
RUN groupadd --gid ${USER_GID} ${USERNAME} \
  && useradd --uid ${USER_UID} --gid ${USER_GID} -m ${USERNAME} \
  && echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/${USERNAME} \
  && chmod 0440 /etc/sudoers.d/${USERNAME}

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 - \
  && ln -s "$POETRY_HOME/bin/poetry" /usr/local/bin/poetry

# Configure Poetry for project-local virtualenvs
RUN sudo -u ${USERNAME} poetry config virtualenvs.in-project true

# Install KataGo binary and sample configs
RUN set -eux; \
  mkdir -p ${KATAGO_ROOT} ${KATAGO_ROOT}/configs ${KATAGO_ROOT}/networks ${KATAGO_ROOT}/default-networks; \
  KATAGO_TMP="/tmp/katago-unpack"; \
  rm -rf "${KATAGO_TMP}"; \
  mkdir -p "${KATAGO_TMP}"; \
  curl -L -o /tmp/katago.zip "https://github.com/lightvector/KataGo/releases/download/v${KATAGO_VERSION}/${KATAGO_PACKAGE}"; \
  unzip -q /tmp/katago.zip -d "${KATAGO_TMP}"; \
  chmod +x "${KATAGO_TMP}/katago"; \
  (cd "${KATAGO_TMP}" && ./katago --appimage-extract >/dev/null); \
  install -d "${KATAGO_ROOT}/appimage/usr"; \
  cp -r "${KATAGO_TMP}/squashfs-root/usr/." "${KATAGO_ROOT}/appimage/usr/"; \
  cp "${KATAGO_TMP}"/*.cfg "${KATAGO_ROOT}/configs/"; \
  cp "${KATAGO_ROOT}/configs/default_gtp.cfg" "${KATAGO_ROOT}/configs/fastgtp.cfg"; \
  sed -i 's|logDir = gtp_logs|logDir = /var/log/katago|g' "${KATAGO_ROOT}/configs/fastgtp.cfg"; \
  printf '#!/usr/bin/env bash\nset -euo pipefail\nHERE="$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")"\nexport LD_LIBRARY_PATH="${HERE}/appimage/usr/lib:${LD_LIBRARY_PATH:-}"\nexec "${HERE}/appimage/usr/bin/katago" "$@"\n' > "${KATAGO_ROOT}/katago"; \
  chmod +x "${KATAGO_ROOT}/katago"; \
  curl -L -o "${KATAGO_ROOT}/default-networks/${KATAGO_NETWORK_BASENAME}" "${KATAGO_NETWORK_URL}"; \
  cp "${KATAGO_ROOT}/default-networks/${KATAGO_NETWORK_BASENAME}" "${KATAGO_ROOT}/networks/${KATAGO_NETWORK_BASENAME}"; \
  ln -sf "${KATAGO_ROOT}/katago" /usr/local/bin/katago; \
  rm -rf "${KATAGO_TMP}" /tmp/katago.zip

# Copy project source for runtime usage and expose it on PYTHONPATH
COPY --chown=${USERNAME}:${USER_GID} fastgtp /opt/fastgtp-app/fastgtp
COPY --chown=${USERNAME}:${USER_GID} pyproject.toml README.md /opt/fastgtp-app/
ENV PYTHONPATH=/opt/fastgtp-app

# Install project runtime dependencies via Poetry
RUN sudo -u ${USERNAME} bash -lc 'cd /opt/fastgtp-app && poetry install --only main --no-root'
ENV PATH=/opt/fastgtp-app/.venv/bin:$PATH

# Prepare runtime defaults for the FastAPI server
ENV FASTGTP_ENGINE="katago gtp -config ${KATAGO_ROOT}/configs/fastgtp.cfg -model ${KATAGO_ROOT}/networks/${KATAGO_NETWORK_BASENAME}" \
  FASTGTP_PORT=8000 \
  FASTGTP_HOST=0.0.0.0

# Provision directory structure expected by KataGo
RUN mkdir -p /var/log/katago \
  && mkdir -p /workspace \
  && chown ${USERNAME}:${USER_GID} /var/log/katago \
  && chown ${USERNAME}:${USER_GID} /workspace \
  && chown -R ${USERNAME}:${USER_GID} ${KATAGO_ROOT}

# Runtime command launches the API server via uvicorn
EXPOSE 8000

CMD ["bash", "-lc", "set -euo pipefail; if [[ -z \"${FASTGTP_ENGINE:-}\" ]]; then echo 'FASTGTP_ENGINE environment variable must be set' >&2; exit 1; fi; NETWORK_BASENAME=\"${KATAGO_NETWORK_BASENAME:-kata1-b28c512nbt-s11233360640-d5406293331.bin.gz}\"; NETWORK_PATH=\"${KATAGO_ROOT}/networks/${NETWORK_BASENAME}\"; FALLBACK_NETWORK=\"${KATAGO_ROOT}/default-networks/${NETWORK_BASENAME}\"; if [[ ! -f \"${NETWORK_PATH}\" && -f \"${FALLBACK_NETWORK}\" ]]; then NETWORK_DIR=$(dirname \"${NETWORK_PATH}\"); mkdir -p \"${NETWORK_DIR}\"; cp \"${FALLBACK_NETWORK}\" \"${NETWORK_PATH}\"; fi; uvicorn fastgtp.server.main:app --host \"${FASTGTP_HOST:-0.0.0.0}\" --port \"${FASTGTP_PORT:-8000}\" --app-dir /opt/fastgtp-app"]

WORKDIR /workspace

USER ${USERNAME}
