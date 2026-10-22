FROM node:22.14.0-alpine3.21 AS build

WORKDIR /app

COPY package*.json ./
# package*.json includes a lockfile when available; do not separately COPY a
# missing lockfile. Installation hooks remain disabled in both paths.
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; else npm install --ignore-scripts --no-audit --no-fund; fi

COPY . .

ARG VITE_DATA_MODE=api
ARG VITE_API_BASE_URL=/api
ENV VITE_DATA_MODE=${VITE_DATA_MODE}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:1.27.4-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

# Nginx listens on IPv4; localhost can resolve to ::1 in Alpine.
HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD wget --no-verbose --tries=1 --spider http://127.0.0.1/health || exit 1
