# ── Stage 1: Build React Assets ───────────────────────────────────────────────
FROM node:20-alpine AS builder

WORKDIR /app

# Install specific pnpm version matching package.json
RUN npm install -g pnpm@10.12.1

# Install dependencies (cached if package files don't change)
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

# Copy source code and build production bundle
COPY . .
RUN pnpm run build

# ── Stage 2: Production Nginx Server ──────────────────────────────────────────
FROM nginx:1.27-alpine AS runner

# Remove default nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom Nginx configuration
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost/health || exit 1

CMD ["nginx", "-g", "daemon off;"]
