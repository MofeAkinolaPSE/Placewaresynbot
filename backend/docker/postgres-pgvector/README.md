Usage

Build the custom Postgres image with pgvector (from repo root):

```bash
# from repo root
docker build -t postgres:18-pgvector -f backend/docker/postgres-pgvector/Dockerfile backend/docker/postgres-pgvector
```

Run a container (example):

```bash
docker run --name pg-pgvector -e POSTGRES_PASSWORD=admin1234 -e POSTGRES_DB=synbot_demo -p 5432:5432 -d postgres:18-pgvector
```

Or update your `docker-compose.yml` to build this image and use it instead of the plain `postgres` image. After the DB is running, create the extension as the `postgres` superuser:

```bash
# Example using psql in a running container
docker exec -it pg-pgvector psql -U postgres -d synbot_demo -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Or from host, if psql is available and network allows
PGPASSWORD=admin1234 psql -h localhost -U postgres -d synbot_demo -c "CREATE EXTENSION IF NOT EXISTS vector;"
```

Troubleshooting

- Ensure you run `CREATE EXTENSION` as a superuser (`postgres`).
- If `CREATE EXTENSION` errors saying library not found, confirm the image was built successfully and the `make install` step ran without errors.
- For production, pin a `pgvector` release or fetch a tagged release instead of `--depth 1`.
