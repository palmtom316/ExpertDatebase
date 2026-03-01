FROM node:20-alpine AS build
WORKDIR /app

COPY src/frontend/package.json src/frontend/package-lock.json ./
RUN npm ci

COPY src/frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine

COPY src/frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
