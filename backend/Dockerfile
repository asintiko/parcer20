# Build TDLib from source (pinned commit on the 1.8.x master line)
FROM python:3.11-slim@sha256:0b23cfb7425d065008b778022a17b1551c82f8b4866ee5a7a200084b7e2eafbf AS tdlib-build

ENV DEBIAN_FRONTEND=noninteractive
# Pinned to an exact tdlib/td commit SHA (NOT a tag -- tdlib does not tag minor
# releases; only v1.8.0 exists). This SHA carries the modern Web App / Mini App
# TL schema (openWebApp ... parameters:webAppOpenParameters, webAppInfo.url:webAppUrl)
# the backend codes against. The Mac-built libtdjson shipped to prod MUST be built
# from this SAME SHA so the schema matches -- Mini App fields drift across TDLib
# builds. See the Mini App feature notes. To bump: pick a new SHA, rebuild locally,
# re-verify td/generate/scheme/td_api.tl, ship the binary.
ARG TDLIB_REF=a17f87c4cff7b90b278d12b91ba0614383aaee82
ARG TDLIB_JOBS=2
WORKDIR /opt/tdlib

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    build-essential \
    cmake \
    gperf \
    zlib1g-dev \
    libssl-dev \
    libreadline-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN git init -q . \
    && git remote add origin https://github.com/tdlib/td.git \
    && git fetch --depth 1 origin ${TDLIB_REF} \
    && git checkout -q FETCH_HEAD \
    && mkdir build \
    && cd build \
    && cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DTD_ENABLE_TESTS=OFF .. \
    && cmake --build . --target install --parallel ${TDLIB_JOBS}

# Runtime image
FROM python:3.11-slim@sha256:0b23cfb7425d065008b778022a17b1551c82f8b4866ee5a7a200084b7e2eafbf

ENV PYTHONUNBUFFERED=1
ENV LD_LIBRARY_PATH=/usr/local/lib
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    zlib1g \
    libssl3 \
    ca-certificates \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy TDLib artifacts
COPY --from=tdlib-build /usr/local/lib/libtdjson.so* /usr/local/lib/
COPY --from=tdlib-build /usr/local/include/td /usr/local/include/td
RUN ldconfig

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code
COPY . .

# Sessions directory (persisted via volume)
RUN mkdir -p /app/sessions/tdlib

ENV PYTHONPATH=/app

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
