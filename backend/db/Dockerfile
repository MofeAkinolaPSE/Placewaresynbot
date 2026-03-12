FROM postgres:18

# Install build deps and build pgvector from source so the `vector` extension is available
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       build-essential \
       ca-certificates \
       git \
       postgresql-server-dev-18 \
    && git clone https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && cd /tmp/pgvector \
    && make \
    && make install \
    && rm -rf /tmp/pgvector \
    && apt-get remove -y git build-essential \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

CMD ["postgres"]
