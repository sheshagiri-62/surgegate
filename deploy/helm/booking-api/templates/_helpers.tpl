{{- define "booking-api.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Values.image.tag | quote }}
app.kubernetes.io/part-of: surgegate
{{- end -}}

{{- define "booking-api.selector" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Database settings shared by the API pods and the migration Job (see app/db.py). */}}
{{- define "booking-api.dbEnv" -}}
- name: AWS_REGION
  value: {{ .Values.aws.region | quote }}
- name: DB_INSTANCE_ID
  value: {{ .Values.database.instanceId | quote }}
- name: QUEUE_TABLE
  value: {{ .Values.queue.table | quote }}
- name: SALE_EVENTS_STREAM
  value: {{ .Values.saleEvents.stream | quote }}
- name: HOLD_TIMER_ARN
  value: {{ .Values.holdTimer.arn | quote }}
- name: BOOKING_PASS_REQUIRED
  value: {{ .Values.bookingPass.required | quote }}
- name: BOOKING_PASS_SECRET_ID
  value: {{ .Values.bookingPass.secretId | quote }}
{{- end -}}


{{/* Cognito settings for JWT checks (app/auth.py). */}}
{{- define "booking-api.authEnv" -}}
- name: COGNITO_USER_POOL_ID
  value: {{ .Values.auth.userPoolId | quote }}
- name: COGNITO_CLIENT_IDS
  value: {{ join "," .Values.auth.clientIds | quote }}
{{- end -}}


{{/* Redis seat-map cache (app/cache.py): TLS + AUTH token from Secrets Manager. */}}
{{- define "booking-api.redisEnv" -}}
- name: REDIS_HOST
  value: {{ .Values.redis.host | quote }}
- name: REDIS_AUTH_SECRET_ID
  value: {{ .Values.redis.authSecretId | quote }}
{{- end -}}


{{/* Browser origins allowed by CORS (empty = no CORS headers). */}}
{{- define "booking-api.corsEnv" -}}
- name: CORS_ALLOW_ORIGINS
  value: {{ join "," .Values.cors.allowOrigins | quote }}
{{- end -}}


{{/* Payments (ADR 004): provider, its keys in Secrets Manager, where buyers may be sent back. */}}
{{- define "booking-api.paymentsEnv" -}}
- name: PAYMENT_PROVIDER
  value: {{ .Values.payments.provider | quote }}
- name: PAYMENT_SECRET_ID
  value: {{ .Values.payments.secretId | quote }}
- name: MOCKPAY_API_URL
  value: {{ .Values.payments.mock.apiUrl | quote }}
- name: MOCKPAY_CHECKOUT_BASE
  value: {{ .Values.payments.mock.checkoutBase | quote }}
- name: ORDER_RETURN_ORIGINS
  value: {{ join "," .Values.payments.returnOrigins | quote }}
{{- end -}}
