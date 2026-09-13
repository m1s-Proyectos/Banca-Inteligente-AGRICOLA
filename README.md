# Banca Inteligente Retell

MVP de cobranza preventiva por llamadas con Retell. El objetivo de la primera demo es probar un flujo completo: clientes sinteticos, programacion de llamada, worker seguro, endpoints para Retell y panel operativo.

## Meta de 12 horas

1. Levantar API, worker, web y PostgreSQL con Docker Compose.
2. Cargar clientes y obligaciones sinteticas.
3. Programar llamadas desde el panel.
4. Evitar llamadas accidentales con `RETELL_ALLOWED_TEST_NUMBERS`.
5. Recibir webhooks y mostrar resultados, transcripcion, sentimiento y estado.

## Arranque

```bash
cp .env.example .env
docker compose build
docker compose up -d db
docker compose run --rm api alembic upgrade head
docker compose run --rm api python -m app.seed
docker compose up -d api worker web
```

Panel: http://localhost:5173

API: http://localhost:8000/docs

## Arranque local sin Docker

Si Docker no esta disponible, se puede usar SQLite para una demo local:

```bash
copy .env.local.example .env
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
$env:PYTHONPATH="backend"
.\.venv\Scripts\python.exe -m app.dev_bootstrap
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

En otra terminal:

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

## Retell

Configurar el tunel HTTPS hacia `http://localhost:8000` y registrar:

- `POST /api/v1/retell/webhooks`
- `POST /api/v1/retell/tools/verify-identity`
- `POST /api/v1/retell/tools/get-assistance-options`
- `POST /api/v1/retell/tools/request-reschedule`

El worker solo llama a numeros incluidos en `RETELL_ALLOWED_TEST_NUMBERS`.
