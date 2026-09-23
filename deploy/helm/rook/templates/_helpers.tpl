{{- define "rook.labels" -}}
app.kubernetes.io/name: rook
app.kubernetes.io/instance: {{ .Release.Name | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service | quote }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | quote }}
{{- end -}}

{{- define "rook.env" -}}
envFrom:
  - configMapRef:
      name: {{ .Release.Name }}-config
env:
  - name: ROOK_DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: {{ .Values.postgres.secret.name | quote }}
        key: {{ .Values.postgres.secret.passwordKey | quote }}
{{- end -}}

{{- define "rook.security" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}
