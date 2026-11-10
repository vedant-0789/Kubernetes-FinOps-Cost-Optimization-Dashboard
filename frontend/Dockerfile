# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# Unprivileged nginx (runs as uid 101, listens on 8080) serves the SPA and
# proxies /api to the backend service, so the browser only talks to one origin.
FROM nginxinc/nginx-unprivileged:1.27-alpine
ENV FINOPS_API_UPSTREAM=http://api:8000
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
