FROM node:22.14.0-alpine3.21 AS build

WORKDIR /app

COPY package*.json ./
# A lockfile should be committed when registry access is available. The fallback
# keeps the current mock-only demo buildable while the lockfile is pending.
COPY package-lock.json* ./
RUN if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; else npm install --ignore-scripts --no-audit --no-fund; fi

COPY . .

ARG VITE_DATA_MODE=mock
ARG VITE_API_BASE_URL=/api
ENV VITE_DATA_MODE=${VITE_DATA_MODE}
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:1.27.4-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=10s --timeout=5s --retries=10 CMD wget --no-verbose --tries=1 --spider http://localhost/health || exit 1
