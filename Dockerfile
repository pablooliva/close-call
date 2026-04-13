FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for aiortc (WebRTC) and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    libssl-dev \
    libgl1 \
    libglib2.0-0 \
    libxcb1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

COPY . .

EXPOSE 7860

CMD ["uv", "run", "python", "server.py"]
