# Build context: repo root. docker build -f infrastructure/docker/web.Dockerfile .
FROM node:24-alpine AS build
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
RUN npm run build

# shortcut: default nginx config has no SPA fallback; add try_files when apps/web gets client-side routes.
FROM nginxinc/nginx-unprivileged:alpine
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
