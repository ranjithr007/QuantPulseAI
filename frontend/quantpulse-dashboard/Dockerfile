FROM node:22-alpine AS build

WORKDIR /app

ARG VITE_BACKEND_URL
ENV VITE_BACKEND_URL=${VITE_BACKEND_URL}

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN test -n "$VITE_BACKEND_URL" \
    && npm run build

FROM nginx:1.27-alpine

ENV PORT=8080
ENV QUANTPULSE_API_UPSTREAM=https://quantpulseai-staging.up.railway.app

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- "http://127.0.0.1:${PORT}/health" >/dev/null || exit 1

CMD ["nginx", "-g", "daemon off;"]
