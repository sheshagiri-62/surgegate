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
