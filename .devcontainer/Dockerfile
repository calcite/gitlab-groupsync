FROM python:3.13-slim

# Install git and other dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip install uv


# Install Backlog.md
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && npm install -g backlog.md \
    && rm -rf /var/lib/apt/lists/*


# Install OpenCode CLI
RUN curl -fsSL https://opencode.ai/install | bash

# Install Claude Code CLI
RUN curl -fsSL https://claude.ai/install.sh | bash
ENV PATH="/root/.local/bin:${PATH}"
