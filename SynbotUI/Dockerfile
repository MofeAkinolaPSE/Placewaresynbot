# ── Stage 1: Build the React SPA ───────────────────────────────────────────
FROM node:22-slim AS builder

WORKDIR /app

# Patch all Debian OS packages to their latest security-fixed versions.
# Closes CVEs that arrive via the node:22-slim base but have upstream fixes
# available in the Debian package registry — without changing the Node version.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# Use corepack (built into Node 22) to activate the exact pnpm version declared
# in package.json. The +sha512 hash is verified by corepack — prevents a
# compromised or yanked pnpm release from silently entering the build.
RUN corepack enable && \
    corepack prepare pnpm@10.14.0+sha512.ad27a79641b49c3e481a16a805baa71817a04bbe06a38d17e60e2eaee83f6a146c6a688125f5792e48dd5ba30e7da52a5cda4c3992b9ccf333f9ce223af84748 --activate

# Drop to the built-in non-root 'node' user before any code runs.
# Nothing below this line requires root privileges.
RUN chown node:node /app
USER node

# Install deps from the lockfile — reproducible and tamper-proof.
COPY --chown=node:node package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source and build.
# VITE_API_BASE_URL is intentionally left empty — nginx proxies API routes.
COPY --chown=node:node . .
RUN pnpm run build:client

# ── Stage 2: Serve with nginx ───────────────────────────────────────────────
# nginx:stable-alpine resolves to the current stable release — a genuinely
# newer image than nginx:1.27-alpine3.21, which shared the exact same layer
# SHA as nginx:1.27-alpine (i.e. a silent alias, zero CVE improvement).
FROM nginx:stable-alpine

# Upgrade all Alpine OS packages to their latest security-patched versions.
# Closes CVEs in musl, busybox, OpenSSL, libexpat, etc. that are present in
# the base layer but have fixes available in the Alpine package registry.
RUN apk --no-cache upgrade

# Remove the default page shipped in the base image before we add ours.
RUN rm -rf /usr/share/nginx/html/*

# Copy built SPA.
# Files are owned by root but readable by the nginx worker (uid 101 on alpine).
# The worker cannot write to them — limits damage if a worker is compromised.
COPY --from=builder --chown=root:nginx /app/dist/spa /usr/share/nginx/html
RUN chmod -R 755 /usr/share/nginx/html

# curl is ~600 kB on alpine and only used by HEALTHCHECK below.
RUN apk add --no-cache curl

# Copy nginx config.
# Note: nginx -t cannot run at build time because the TLS certificates
# (/etc/ssl/placeware/cert.pem and key.pem) are mounted as a runtime volume
# and do not exist inside the image layer. Config syntax is validated on startup.
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY security-headers.conf /etc/nginx/snippets/security-headers.conf

# Remove the base image's IPv6 auto-config entrypoint script.
#
# That script wants to append a "listen [::]:80" to /etc/nginx/conf.d/default.conf
# when it doesn't already have one -- which ours doesn't, by design. Before
# editing it, the script checks whether the file is the stock one by running
# `apk manifest nginx`, and THAT reaches out to the Alpine package CDN on every
# container start. Where outbound access is blocked or filtered -- the normal
# situation for an on-premises client server -- the call hangs, the entrypoint
# never finishes, and nginx never starts: the container reports "up" while
# serving nothing. Observed here taking the frontend down on every deploy until
# the hung process was killed by hand.
#
# Deleting it only disables that auto-injection. Both listen directives are set
# explicitly in nginx.conf, so behaviour is unchanged -- startup simply no
# longer depends on an external network call. The image's other entrypoint
# scripts (envsubst templating, worker tuning) are untouched.
RUN rm -f /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh

# Nginx master runs as root to bind privileged ports 80/443.
# Worker processes automatically drop to the 'nginx' user (uid 101).
EXPOSE 80 443

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fs http://localhost/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
