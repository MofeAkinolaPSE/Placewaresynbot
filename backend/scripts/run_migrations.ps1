Param(
    [string]$DatabaseUrl = $env:DATABASE_URL
)

if (-not $DatabaseUrl) {
    Write-Host "DATABASE_URL not set. Using default: postgresql://postgres:postgres@localhost:5432/postgres"
    $DatabaseUrl = "postgresql://postgres:postgres@localhost:5432/postgres"
}

Write-Host "Using DATABASE_URL=$DatabaseUrl"
python .\backend\scripts\apply_migrations.py
