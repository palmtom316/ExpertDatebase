FROM nginx:1.27-alpine

COPY src/frontend/index.html /usr/share/nginx/html/index.html
COPY src/frontend/main.js /usr/share/nginx/html/main.js
COPY src/frontend/styles.css /usr/share/nginx/html/styles.css
COPY src/frontend/nginx.conf /etc/nginx/conf.d/default.conf
