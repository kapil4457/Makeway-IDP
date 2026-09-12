# Platform UI — build the Vite SPA, serve it from nginx in the ECS cluster.
#
# nginx (nginx.conf) also reverse-proxies the control-plane API paths, so the
# browser talks to a single origin through the ALB: no CORS, no mixed content,
# and the control plane itself stays unreachable from the internet.
#
# Build/push is automated by .github/workflows/build-frontend.yaml; the image
# lands on Docker Hub as kapil4457/makeway-frontend:{latest,<sha>}.

FROM node:22-alpine AS build
WORKDIR /app

# Same-origin API calls in prod: client.ts resolves
# `import.meta.env.VITE_API_BASE_URL ?? '/api'` — an empty string is KEPT (the
# /api fallback only applies when the var is unset), so requests go to real
# paths like /app/create and nginx proxies them to the control plane.
# (Dev differs on purpose: `npm run dev` uses the /api Vite proxy instead.)
ENV VITE_API_BASE_URL=""

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80