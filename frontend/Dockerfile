# syntax=docker/dockerfile:1
# ---------- Eitaa Support Desk :: frontend ----------
# Bun-based build + nginx serve (bun is also the runtime package manager).

FROM oven/bun:1.3-slim AS build
WORKDIR /app
COPY package.json ./
RUN bun install --frozen-lockfile || bun install
COPY . .
RUN bun run build

FROM nginx:1.29-alpine AS serve
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
