# Frontend (PDADS MVP)

## Local run

1. Install dependencies:

```bash
npm install
```

2. Configure API URL (optional, default is http://127.0.0.1:8889):

```bash
cp .env.example .env
```

3. Start dev server:

```bash
npm run dev
```

## Checks

```bash
npm run lint
npm run build
```

## Notes

- Auth uses backend endpoints: /auth/register, /auth/login, /auth/me.
- Feed uses backend endpoints: /feed/me and /feed/interactions.
