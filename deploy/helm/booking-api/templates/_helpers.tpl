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
