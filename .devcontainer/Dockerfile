FROM nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04

ARG USERNAME=vscode
ARG USER_UID=1000
ARG USER_GID=1000
ARG KATAGO_VERSION=1.16.3
ARG KATAGO_PACKAGE=katago-v${KATAGO_VERSION}-cuda12.1-cudnn8.9.7-linux-x64.zip

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
    && rm -rf /var/lib/apt/lists/*

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
RUN mkdir -p ${KATAGO_ROOT} ${KATAGO_ROOT}/networks \
    && curl -L -o /tmp/katago.zip "https://github.com/lightvector/KataGo/releases/download/v${KATAGO_VERSION}/${KATAGO_PACKAGE}" \
    && unzip -q /tmp/katago.zip -d ${KATAGO_ROOT} \
    && chmod +x ${KATAGO_ROOT}/katago \
    && ln -s ${KATAGO_ROOT}/katago /usr/local/bin/katago \
    && rm -f /tmp/katago.zip

# Prepare workspace directory and set ownership
RUN mkdir -p /workspace \
    && chown ${USERNAME}:${USER_GID} /workspace \
    && chown -R ${USERNAME}:${USER_GID} ${KATAGO_ROOT}

WORKDIR /workspace

USER ${USERNAME}
