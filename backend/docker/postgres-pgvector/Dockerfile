FROM postgres:18

# Install build dependencies, build pgvector, install, then clean up
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        build-essential \
        git \
        wget \
        postgresql-server-dev-18 \
    && git clone --depth 1 https://github.com/pgvector/pgvector.git /tmp/pgvector \
    && make -C /tmp/pgvector \
    && make -C /tmp/pgvector install \
    && rm -rf /tmp/pgvector \
    && apt-get purge -y --auto-remove build-essential git \
    && rm -rf /var/lib/apt/lists/*

# Expose default Postgres port
EXPOSE 5432

# Use default postgres entrypoint/cmd
