# PR.ADS Frontend

Frontend app path: `app/frontend`.

## Local run

```bash
npm install
npm run dev
```

Default local URL: `http://localhost:5173`.

## Build

```bash
npm run build
npm run preview
```

## Required env

Create `.env` in `app/frontend`:

```bash
VITE_API_BASE_URL=https://<your-railway-backend-domain>/api
```

Use `/api` only when backend is reverse-proxied on the same host.

## OAuth buttons

OAuth buttons are enabled from backend response:

- `GET /api/auth/oauth/providers`

If provider credentials are missing in backend env, the button is disabled.
