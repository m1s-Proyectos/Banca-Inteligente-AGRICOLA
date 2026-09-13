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

Agente: **Sofía — Recordatorio Preventivo** (`agent_270ec9df7856155ae90bbcc096`, conversation flow,
versión publicada `1`). Su configuración en Retell ya apunta al backend de Render:

| Retell | URL |
| --- | --- |
| Webhook del agente | `POST https://banca-inteligente.onrender.com/api/v1/retell/webhooks` |
| Tool `verify-identity` | `POST .../api/v1/retell/tools/verify-identity` |
| Tool `get-assistance-options` | `POST .../api/v1/retell/tools/get-assistance-options` |
| Tool `request-reschedule` | `POST .../api/v1/retell/tools/request-reschedule` |

Los dos sentidos de la integración:

- **Backend → Retell.** El worker toma un `CallJob` pendiente dentro de la ventana hábil y llama a
  `POST /v2/create-phone-call` con `override_agent_id` + `override_agent_version` y las variables
  dinámicas del cliente. Solo marca números presentes en `RETELL_ALLOWED_TEST_NUMBERS`; sin
  `RETELL_FROM_NUMBER` el trabajo queda `SIMULATED` en vez de llamar.
- **Retell → Backend.** Durante la llamada el agente invoca las tools de arriba y, al terminar,
  Retell manda `call_started` / `call_ended` / `call_analyzed` al webhook. Retell firma **webhooks y
  tool calls** con `X-Retell-Signature` (`v=<ms>,d=<hmac-sha256(body+ts, api_key)>`); con
  `RETELL_REQUIRE_SIGNATURE=true` el backend rechaza cualquier petición sin firma válida.

### Demo por web call (sin SIP trunk)

No hace falta número ni troncal SIP: el panel abre la llamada por WebRTC desde el navegador.

1. En el panel, elegir un cliente y pulsar **Iniciar llamada web**.
2. El backend crea el `CallJob` + `Call`, pide `POST /v3/create-web-call` a Retell y devuelve
   `call_id`, `access_token`, `transport` e `ice_servers`. El token es efímero y nunca se persiste.
3. `retell-client-js-sdk` conecta el audio del navegador con esos datos; el agente habla y llama a
   las tools contra el mismo backend. El `transport` viene de Retell y hay que pasarlo tal cual: los
   tokens de `livekit` y `gateway` son indistinguibles y el SDK asume `livekit` si no se le dice.
4. Al colgar, el webhook cierra el ciclo y el panel refresca resultados y transcripción.

`POST /api/v1/retell/web-calls` solo responde con `FAKE_DATA_ONLY=true` y tiene un cooldown global de
10 s para que la demo pública no gaste créditos de Retell.

El botón **Programar llamada telefónica** sigue disponible y ejercita el camino del worker.

## Deploy

### Render (API + worker)

Servicio en producción: <https://banca-inteligente.onrender.com> (`srv-daj2vt15efls73fdc04g`,
rama `main`, autodeploy por commit) con Postgres `banca-inteligente-db` en plan free.

Variables de entorno del servicio:

| Clave | Valor |
| --- | --- |
| `DATABASE_URL` | cadena interna de `banca-inteligente-db` |
| `RETELL_API_KEY` | *secreto* (la misma clave con la que Retell firma) |
| `RETELL_AGENT_ID` | `agent_270ec9df7856155ae90bbcc096` |
| `RETELL_AGENT_VERSION` | `1` |
| `RETELL_REQUIRE_SIGNATURE` | `true` |
| `RUN_WORKER_IN_WEB` | `true` |
| `FAKE_DATA_ONLY` | `true` |
| `RETELL_FROM_NUMBER` / `RETELL_ALLOWED_TEST_NUMBERS` | vacíos mientras no haya SIP trunk |

En plan free no hay un servicio `worker` aparte: con `RUN_WORKER_IN_WEB=true` el bucle del worker
corre como tarea del lifespan de FastAPI, en el mismo proceso que la API. Al contratar un plan de
pago, poner la variable en `false` y levantar el worker con `python -m app.worker.runner`.

`render.yaml` describe esa topología para recrearla desde cero. Validar con:

```bash
render blueprints validate
```

### Vercel (panel)

Panel en <https://banca-inteligente-one.vercel.app> con
`VITE_API_URL=https://banca-inteligente.onrender.com/api/v1`. Ese origen ya está en `cors_origins`
del backend.
