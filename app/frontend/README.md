# Makeway Console — frontend

> [Documentation index](../../docs/README.md) › Components › Frontend

The web UI for the Makeway control plane: log in, browse the app catalog, create an
app through the golden-path form, watch each request reconcile environment by
environment, and register the clusters apps deploy onto.

React 19 single-page app (TypeScript + Vite), Tailwind CSS v4, and a small set of
shadcn-style primitives under [src/components/ui/](src/components/ui/).

## Pages

| Route | Page | What it does |
|---|---|---|
| `/login` | [login.tsx](src/pages/login.tsx) | Sign in against the control plane `/auth` endpoints |
| `/` | [apps.tsx](src/pages/apps.tsx) | App catalog — every app with its request status |
| `/apps/new` | [new-app.tsx](src/pages/new-app.tsx) | Golden-path app creation form (services, environments, capabilities, `access_to`) |
| `/apps/:appName` | [app-detail.tsx](src/pages/app-detail.tsx) | Per-environment services/capabilities, request history, update (`update-app-sheet`) and delete-env (`delete-env-dialog`) actions |
| `/clusters` | [clusters.tsx](src/pages/clusters.tsx) | Cluster registry — register/refresh a cluster's endpoint, token, CA (`register-cluster-sheet`) |
| `/profile` | [profile.tsx](src/pages/profile.tsx) | The signed-in user |
| `*` | [not-found.tsx](src/pages/not-found.tsx) | 404 |

Routing lives in [src/App.tsx](src/App.tsx). [require-auth.tsx](src/components/layout/require-auth.tsx)
guards the authenticated routes; session state comes from [use-session.ts](src/hooks/use-session.ts)
and [lib/auth/session.ts](src/lib/auth/session.ts).

## Talking to the control plane

All API access goes through [src/lib/api/client.ts](src/lib/api/client.ts):

```ts
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '/api'
```

- **Local dev** — leave `VITE_API_BASE_URL` unset. Requests go to `/api`, which the
  Vite dev server proxies to the control plane (see `vite.config.ts`).
- **In-cluster** — the [Dockerfile](Dockerfile) builds with `VITE_API_BASE_URL=""` and
  serves the SPA from [nginx](nginx.conf), which reverse-proxies the control-plane
  route prefixes (`/app`, `/auth`, `/cluster`, `/docs`, …) to
  `control-plane.makeway.internal:8000` — same origin, no CORS.
- Typed endpoints live in [src/lib/api/endpoints.ts](src/lib/api/endpoints.ts) with
  response types in [src/lib/api/types.ts](src/lib/api/types.ts); server state is cached
  with React Query ([use-api.ts](src/hooks/use-api.ts)).

## Develop

```bash
npm install
npm run dev        # vite dev server
npm run lint       # oxlint
npm run build      # tsc -b && vite build
npm run preview    # serve the production build locally
```

## Deploy

`deploy-frontend.yaml` builds the image (`build-frontend.yaml` publishes it to Docker
Hub) and Terraform rolls it onto the same ECS cluster as the control plane, behind the
ALB. The platform-side configuration is described in the
[root README](../../README.md#configuration-reference).
