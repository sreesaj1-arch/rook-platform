FROM node:24.15.0-bookworm-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html tsconfig.json vite.config.ts ./
COPY src ./src
RUN npm run build

FROM nginx:1.30.5-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/rook.conf.template
ENV ROOK_API_UPSTREAM=api:8000
USER 10001:10001
EXPOSE 8080
ENTRYPOINT ["/bin/sh", "-c"]
CMD ["envsubst '${ROOK_API_UPSTREAM}' < /etc/nginx/rook.conf.template > /tmp/nginx.conf && exec nginx -c /tmp/nginx.conf -g 'daemon off;'"]
