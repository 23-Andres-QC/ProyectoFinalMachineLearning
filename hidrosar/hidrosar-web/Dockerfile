FROM node:24-alpine AS compilar
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:stable-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=compilar /app/dist /usr/share/nginx/html
EXPOSE 80
