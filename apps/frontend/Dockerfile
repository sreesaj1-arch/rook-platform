FROM node:24.15.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build

# Same Nginx version; omit unused image-filter/fontconfig/libexpat dependencies.
FROM nginx:1.30.5-alpine3.24-slim@sha256:32463212baf0e7d91aded2e9b843a4f2b9e017804b8c9d5bae7b51dcef64389c
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/rook.conf.template
ENV ROOK_API_UPSTREAM=api:8000
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["envsubst '${ROOK_API_UPSTREAM}' < /etc/nginx/rook.conf.template > /tmp/nginx.conf && exec nginx -c /tmp/nginx.conf -g 'daemon off;'"]
