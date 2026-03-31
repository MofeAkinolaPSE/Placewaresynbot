# ── Stage 1: Build the React SPA ───────────────────────────────────────────
FROM node:20-slim AS builder

WORKDIR /app

# Install pnpm
RUN npm install -g pnpm

# Install dependencies (respects pnpm-lock.yaml for reproducible builds)
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build
# VITE_API_BASE_URL is intentionally left empty — nginx proxies API routes
COPY . .
RUN pnpm run build:client

# ── Stage 2: Serve with nginx ───────────────────────────────────────────────
FROM nginx:1.27-alpine

# Copy built SPA
COPY --from=builder /app/dist/spa /usr/share/nginx/html

# Copy nginx proxy config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
