# Build TDLib from source (v1.8.26)
FROM python:3.11-slim AS tdlib-build

ENV DEBIAN_FRONTEND=noninteractive
ARG TDLIB_REF=master
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

RUN git clone --branch ${TDLIB_REF} --depth 1 https://github.com/tdlib/td.git . \
    && mkdir build \
    && cd build \
    && cmake -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/local -DTD_ENABLE_TESTS=OFF .. \
    && cmake --build . --target install --parallel ${TDLIB_JOBS}

# Runtime image
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV LD_LIBRARY_PATH=/usr/local/lib:${LD_LIBRARY_PATH}
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    zlib1g \
    libssl3 \
    ca-certificates \
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

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
