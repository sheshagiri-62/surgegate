# syntax=docker/dockerfile:1
# Small, non-root image for the booking API.
FROM python:3.12-slim AS build
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.12-slim
ARG APP_VERSION=dev
ENV APP_VERSION=${APP_VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
