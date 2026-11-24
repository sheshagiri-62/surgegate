# syntax=docker/dockerfile:1
# Organiser dashboard (Next.js SSR, standalone). Non-root, read-only root filesystem
# (.next/cache is an emptyDir in the chart).
FROM node:24-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
ARG APP_VERSION=dev
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-slim
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=8000 HOSTNAME=0.0.0.0
WORKDIR /app
COPY --from=build --chown=1000:1000 /app/.next/standalone ./
COPY --from=build --chown=1000:1000 /app/.next/static ./.next/static
USER 1000
EXPOSE 8000
CMD ["node", "server.js"]
