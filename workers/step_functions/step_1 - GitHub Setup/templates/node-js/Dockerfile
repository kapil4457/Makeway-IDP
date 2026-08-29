FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

COPY . .

ARG SERVICE_NAME=__SERVICE_NAME__
ENV SERVICE_NAME=${SERVICE_NAME}

EXPOSE 3000

CMD ["node", "server.js"]