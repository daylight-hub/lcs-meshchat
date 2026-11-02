# syntax=docker/dockerfile:1.7
# Build the frontend
FROM node:20-bookworm-slim AS build-frontend

WORKDIR /src

# Copy required source files
COPY *.json .
COPY *.js .
COPY src/frontend ./src/frontend

# Install NodeJS deps, exluding electron
RUN npm install --omit=dev && \
  npm run build-frontend

# Tor for LCS Global's "Connect through Tor" switch, built from the reviewed source release that
# is kept in this repository (tools/tor/tor-0.4.9.15.tar.gz): nothing is downloaded. It must match
# the SHA-256 published and signed by the Tor Project (tools/tor/*.sha256sum, *.asc), or the build
# stops. configure/Makefile are regenerated from configure.ac instead of trusting the shipped ones,
# and the relay and directory-authority code is left out: this tor can only ever be a client.
# Debian supplies only the compiler and the three libraries tor links against (libevent, OpenSSL, zlib).
FROM debian:bookworm-slim AS build-tor
ARG TOR_VERSION=0.4.9.15
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential autoconf automake libtool pkg-config \
        libevent-dev libssl-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /tor
COPY tools/tor/tor-${TOR_VERSION}.tar.gz tools/tor/tor-${TOR_VERSION}.tar.gz.sha256sum ./
RUN sha256sum -c "tor-${TOR_VERSION}.tar.gz.sha256sum" \
    && tar -xzf "tor-${TOR_VERSION}.tar.gz" \
    && cd "tor-${TOR_VERSION}" \
    && rm -f configure Makefile.in aclocal.m4 && autoreconf -fi \
    && ./configure --prefix=/opt/tor --disable-module-relay --disable-module-dirauth \
         --disable-asciidoc --disable-manpage --disable-html-manual --disable-unittests \
    && make -j"$(nproc)" src/app/tor \
    && install -D -m 755 src/app/tor /opt/tor/bin/tor \
    && install -D -m 644 src/config/geoip /opt/tor/share/tor/geoip \
    && install -D -m 644 src/config/geoip6 /opt/tor/share/tor/geoip6 \
    && install -D -m 644 LICENSE /opt/tor/share/tor/LICENSE \
    && /opt/tor/bin/tor --version | grep -q "Tor version ${TOR_VERSION}\."

# Main app build
FROM python:3.11-bookworm

WORKDIR /app

# Install system libraries required by LXST for call audio.
# libopus0 provides the Opus codec used to encode/decode telephone audio;
# without it, incoming/outgoing calls fail with "Opus library wasn't found".
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libopus0 \
        libopusfile0 \
        libopusenc0 \
        opus-tools \
    && rm -rf /var/lib/apt/lists/*

# Tor (off unless switched on in the app); its runtime libraries come from Debian
RUN apt-get update && apt-get install -y --no-install-recommends libevent-2.1-7 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build-tor /opt/tor/bin/tor /usr/local/bin/tor
COPY --from=build-tor /opt/tor/share/tor /usr/local/share/tor
ENV LCS_TOR_PATH=/usr/local/bin/tor

# Install Python deps
COPY ./requirements.txt .
RUN pip install -r requirements.txt

# Copy prebuilt frontend
COPY --from=build-frontend /src/public public

# Copy other required source files
COPY *.py .
COPY src/__init__.py ./src/__init__.py
COPY src/backend ./src/backend
COPY *.json .

CMD ["python", "meshchat.py", "--host=0.0.0.0", "--reticulum-config-dir=/config/.reticulum", "--storage-dir=/config/.meshchat", "--headless"]
