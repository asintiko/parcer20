# Parcer 2.0 Review Source Archive

- Generated at: 2026-04-02
- Source root: `/Users/kulacidmyt/Documents/parcer2.0`
- Archive purpose: engineering review of current source code
- Desktop release version in source: `1.4.4`
- Git metadata: unavailable in this restored workspace (`.git` is not present)

## Included

- `backend/`
- `frontend/src/`
- `frontend/electron/`
- `frontend/build/`
- `frontend/package.json`
- `frontend/package-lock.json`
- `frontend/vite.config.ts`
- `frontend/tsconfig.json`
- `frontend/tsconfig.node.json`
- `frontend/postcss.config.js`
- `frontend/tailwind.config.js`
- `mini-app/`
- `deploy/`
- `security/client-access.example.json`
- `security/root-access.server.example.json`
- `.env.example`
- `README.md`
- `docker-compose.yml`
- `docker-compose.dev.yml`
- `ARCHIVE_MANIFEST.md`

## Excluded

- `.git/`
- `.env`
- real security secrets and runtime config:
  - `security/client-access.json`
  - `security/root-access.server.json`
  - `frontend/client-access.json`
  - `frontend/public/client-access.json`
- generated and heavy folders:
  - `backend/sessions/`
  - `frontend/node_modules/`
  - `frontend/dist/`
  - `frontend/release/`
  - `frontend/public/tweb/`
  - `windows-customer-bundle/`
  - `pdf_receipt_bot/`
  - `.venv311/`
  - `__pycache__/`
  - `.DS_Store`
- dumps, archives, screenshots, caches, temporary files

## Rebuild Notes

### Frontend desktop

```bash
cd frontend
npm ci
npm run build
npm run electron:build
```

### Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Mini App

```bash
cd mini-app
npm ci
npm run build
```
