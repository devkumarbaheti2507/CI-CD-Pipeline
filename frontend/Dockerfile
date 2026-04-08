# ── Stage 1: build React app ──────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Accept backend URLs as build-time args (override in docker-compose or CI)
ARG REACT_APP_CONTROLLER_URL=http://localhost:9000
ARG REACT_APP_ANALYZER_URL=http://localhost:5001
ARG REACT_APP_CLASSIFIER_URL=http://localhost:8000
ARG REACT_APP_RECOVERY_URL=http://localhost:6001
ARG REACT_APP_NOTIFICATION_URL=http://localhost:7000

ENV REACT_APP_CONTROLLER_URL=$REACT_APP_CONTROLLER_URL
ENV REACT_APP_ANALYZER_URL=$REACT_APP_ANALYZER_URL
ENV REACT_APP_CLASSIFIER_URL=$REACT_APP_CLASSIFIER_URL
ENV REACT_APP_RECOVERY_URL=$REACT_APP_RECOVERY_URL
ENV REACT_APP_NOTIFICATION_URL=$REACT_APP_NOTIFICATION_URL

# CI="" prevents react-scripts from treating warnings as errors
ENV CI=""
RUN npm run build

# ── Stage 2: serve with nginx ─────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# Copy built assets
COPY --from=build /app/build /usr/share/nginx/html

# Single-page app routing: serve index.html for all routes
RUN printf 'server {\n\
    listen 80;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
