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
# The API target is deployment-specific.  Do not silently fall back to the
# retired staging service: a missing upstream should fail the container health
# check and prompt the operator to configure the cloud service correctly.
ENV QUANTPULSE_API_UPSTREAM=

COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- "http://127.0.0.1:${PORT}/health" >/dev/null || exit 1

CMD ["sh", "-c", "if [ -z \"$QUANTPULSE_API_UPSTREAM\" ]; then echo 'QUANTPULSE_API_UPSTREAM must be configured for the frontend service' >&2; exit 1; fi; exec nginx -g 'daemon off;'"]
