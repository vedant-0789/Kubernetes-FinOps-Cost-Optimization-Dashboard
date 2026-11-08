{{- define "finops.fullname" -}}
{{- if contains .Chart.Name .Release.Name -}}{{ .Release.Name | trunc 50 | trimSuffix "-" }}
{{- else -}}{{ printf "%s-%s" .Release.Name .Chart.Name | trunc 50 | trimSuffix "-" }}{{- end -}}
{{- end -}}

{{- define "finops.labels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version }}
{{- end -}}

{{- define "finops.selector" -}}
app.kubernetes.io/name: {{ .root.Chart.Name }}
app.kubernetes.io/instance: {{ .root.Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "finops.serverImage" -}}
{{ .Values.image.server.repository }}:{{ .Values.image.server.tag | default .Chart.AppVersion }}
{{- end -}}

{{- define "finops.uiImage" -}}
{{ .Values.image.ui.repository }}:{{ .Values.image.ui.tag | default .Chart.AppVersion }}
{{- end -}}

{{- define "finops.secretName" -}}
{{ .Values.secrets.existingSecret | default (printf "%s-secrets" (include "finops.fullname" .)) }}
{{- end -}}

{{- define "finops.dbHost" -}}
{{ include "finops.fullname" . }}-db
{{- end -}}

{{/* Environment shared by API, worker and migration init container. */}}
{{- define "finops.env" -}}
envFrom:
  - configMapRef:
      name: {{ include "finops.fullname" . }}-config
  - secretRef:
      name: {{ include "finops.secretName" . }}
{{- end -}}

{{- define "finops.pod" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets: {{ toYaml . | nindent 2 }}
{{- end }}
securityContext: {{ toYaml .Values.podSecurityContext | nindent 2 }}
{{- with .Values.nodeSelector }}
nodeSelector: {{ toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.tolerations }}
tolerations: {{ toYaml . | nindent 2 }}
{{- end }}
{{- with .Values.affinity }}
affinity: {{ toYaml . | nindent 2 }}
{{- end }}
{{- end -}}
