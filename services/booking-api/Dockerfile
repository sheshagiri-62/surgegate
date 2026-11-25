# syntax=docker/dockerfile:1
# Small, non-root image for the booking API.
# Alpine (Day 10 Task 3): python:3.12-slim (Debian 13) had 54 HIGH findings with no fixed
# version (openssl, util-linux, ...); this image has 0 fixable HIGH/CRITICAL after apk upgrade.
FROM python:3.12.16-alpine3.24 AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12.16-alpine3.24
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# Security updates published after the base image was built (e.g. krb5-libs).
RUN apk upgrade --no-cache && adduser -D -H -u 10001 -s /sbin/nologin app
COPY --from=build /install /usr/local
WORKDIR /srv
# RDS CA bundle: the app verifies the database's TLS certificate (sslmode=verify-full).
# Create the directory first: ADD --chmod would give a NEW parent directory mode 644 too
# (no execute bit), which the non-root user cannot enter.
RUN mkdir -m 755 /srv/certs
ADD --chmod=644 https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem /srv/certs/rds-global-bundle.pem
COPY alembic.ini ./
COPY alembic ./alembic
COPY app ./app
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--timeout-graceful-shutdown", "20"]
