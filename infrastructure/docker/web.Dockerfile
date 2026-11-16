# Build context: repo root. docker build -f infrastructure/docker/web.Dockerfile .
FROM node:24-alpine AS build
WORKDIR /repo/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
COPY packages/shared-types /repo/packages/shared-types
RUN npm run build

FROM nginxinc/nginx-unprivileged:alpine
COPY infrastructure/docker/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
