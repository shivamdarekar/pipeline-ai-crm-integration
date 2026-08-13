# Pipeline – HubSpot Integration Architecture

## 1. System Overview

Pipeline is a SaaS integration platform. A React frontend communicates with a FastAPI backend that handles OAuth flows and CRM data fetching for each provider. Redis is used exclusively for short-lived OAuth state and credential handoff.

The application ships with Airtable and Notion integrations. HubSpot is added following the same architecture contract.

### High-Level Architecture

```text
                         Browser
                            │
                 ┌──────────┴──────────┐
                 │                     │
             React :3000          HubSpot Popup
                 │                     │
                 │ Axios               │ OAuth
                 ▼                     ▼
            FastAPI :8000        HubSpot OAuth
                 │                     │
       ┌─────────┼─────────┐           │
       │         │         │           │
       │       Redis    HubSpot ───────┘
       │      :6379        API
       │         │         │
       └─────────┴─────────┘
                 │
                 ▼
        IntegrationItem[]
                 │
                 ▼
              React UI
```

### Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React + Material UI | Integration UI and data display |
| HTTP client | Axios | Frontend → FastAPI requests |
| Backend | FastAPI (Python) | OAuth callbacks and integration API |
| Async HTTP | HTTPX | Backend → HubSpot token exchange |
| Sync HTTP | requests | Backend → HubSpot CRM API (pagination loop) |
| Temporary storage | Redis | OAuth state and short-lived credential handoff |
| External API | HubSpot CRM API | Contacts, Companies, Deals |
| Data model | `IntegrationItem` | Provider-independent normalized record format |

---

## 2. Component Breakdown

### Frontend

#### `src/integration-form.js`
- Collects `user_id` and `org_id` from input fields
- Renders the provider selector (Notion, Airtable, HubSpot)
- Mounts the selected provider's integration component
- Holds `integrationParams` state — passes credentials down to `DataForm` once set

Provider mapping:
```javascript
const integrationMapping = {
  Notion: NotionIntegration,
  Airtable: AirtableIntegration,
  HubSpot: HubSpotIntegration,
};
```

#### `src/integrations/hubspot.js`
- Renders the `Connect to HubSpot` button
- On click: POSTs to `/integrations/hubspot/authorize`, receives the OAuth URL, opens it in a 600×600 popup
- Polls `window.setInterval` every 200ms to detect when the popup closes
- On popup close: POSTs to `/integrations/hubspot/credentials` to retrieve tokens
- Sets `integrationParams` with `{ credentials, type: 'HubSpot' }` to unlock the data form
- Button state: idle → spinner (connecting) → green "HubSpot Connected"

#### `src/data-form.js`
- Shared across all providers via `endpointMapping`
- On "Load Data": POSTs credentials to `/integrations/{provider}/load`
- Pretty-prints the returned `IntegrationItem[]` as JSON in a multiline text field
- "Clear Data" resets the display

---

### Backend

#### `main.py`
FastAPI application entry point. Configures CORS using `FRONTEND_URL` from env. Route layer is intentionally thin — receives form data and delegates to the provider module.

HubSpot routes:

| Method | Route | Handler |
|---|---|---|
| POST | `/integrations/hubspot/authorize` | `authorize_hubspot` |
| GET | `/integrations/hubspot/oauth2callback` | `oauth2callback_hubspot` |
| POST | `/integrations/hubspot/credentials` | `get_hubspot_credentials` |
| POST | `/integrations/hubspot/load` | `get_items_hubspot` |

#### `integrations/hubspot.py`
All HubSpot-specific logic lives here:

1. Reads OAuth config from environment variables at module load
2. Builds `AUTHORIZATION_URL` from `CLIENT_ID`, `REDIRECT_URI`, and `SCOPES`
3. `authorize_hubspot` — generates state, stores in Redis, returns full auth URL
4. `oauth2callback_hubspot` — validates state, exchanges code for tokens, stores credentials in Redis
5. `get_hubspot_credentials` — reads and deletes credentials from Redis
6. `_fetch_hubspot_objects` — synchronous paginated CRM fetcher
7. `create_integration_item_metadata_object` — maps HubSpot JSON to `IntegrationItem`
8. `get_items_hubspot` — orchestrates fetching all three object types

#### `redis_client.py`
Thin async Redis wrapper using `redis.asyncio`. Exposes:
- `add_key_value_redis(key, value, expire)` — set with optional TTL
- `get_value_redis(key)` — get
- `delete_key_redis(key)` — delete

Redis connection reads `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB` from environment.

---

## 3. HubSpot OAuth Flow — Detailed

```text
┌─────────────────────────────────────────────────────────────────┐
│  React                                                          │
│    │                                                            │
│    │  1. POST /integrations/hubspot/authorize                   │
│    │     { user_id, org_id }                                    │
│    ▼                                                            │
│  FastAPI                                                        │
│    │  2. generate secrets.token_urlsafe(32) → state            │
│    │  3. base64-encode { state, user_id, org_id }              │
│    │  4. store state in Redis                                   │
│    │     key: hubspot_state:{org_id}:{user_id}                 │
│    │     TTL: 600s                                              │
│    │  5. build authorization URL:                               │
│    │     https://app.hubspot.com/oauth/authorize                │
│    │     ?client_id=...&redirect_uri=...&scope=...&state=...   │
│    │  6. return URL to React                                    │
│    ▼                                                            │
│  React                                                          │
│    │  7. window.open(authURL) → HubSpot popup                  │
│    │  8. setInterval poll every 200ms for popup.closed         │
│    ▼                                                            │
│  HubSpot (popup)                                               │
│    │  9. user reviews and grants scopes                        │
│    │ 10. HubSpot redirects to:                                 │
│    │     /integrations/hubspot/oauth2callback?code=...&state=..│
│    ▼                                                            │
│  FastAPI /oauth2callback                                        │
│    │ 11. decode base64 state → { state, user_id, org_id }     │
│    │ 12. get saved state from Redis                            │
│    │ 13. compare state values → reject if mismatch/missing     │
│    │ 14. asyncio.gather:                                        │
│    │       POST https://api.hubapi.com/oauth/2026-03/token     │
│    │         grant_type=authorization_code                      │
│    │         code, client_id, client_secret, redirect_uri      │
│    │       + delete hubspot_state key from Redis               │
│    │ 15. on 200: store tokens in Redis                         │
│    │     key: hubspot_credentials:{org_id}:{user_id}           │
│    │     TTL: 600s                                              │
│    │ 16. return <script>window.close()</script>                │
│    ▼                                                            │
│  React (popup closes, poll detects it)                         │
│    │ 17. POST /integrations/hubspot/credentials                │
│    │     { user_id, org_id }                                   │
│    ▼                                                            │
│  FastAPI                                                        │
│    │ 18. get credentials from Redis                            │
│    │ 19. delete key from Redis                                 │
│    │ 20. return { access_token, refresh_token, expires_in }   │
│    ▼                                                            │
│  React                                                          │
│    │ 21. setIntegrationParams({ credentials, type: 'HubSpot'})│
│    │ 22. button → "HubSpot Connected"                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. CRM Data Flow — Detailed

```text
┌─────────────────────────────────────────────────────────────────┐
│  React                                                          │
│    │  POST /integrations/hubspot/load                          │
│    │  { credentials: JSON.stringify({ access_token, ... }) }   │
│    ▼                                                            │
│  FastAPI → get_items_hubspot()                                  │
│    │  parse credentials JSON                                    │
│    │  extract access_token                                      │
│    │                                                            │
│    │  for each object type:                                     │
│    │  ┌─────────────────────────────────────────────────────┐  │
│    │  │  Contact  → /crm/v3/objects/contacts                │  │
│    │  │             properties: firstname, lastname, email   │  │
│    │  │  Company  → /crm/v3/objects/companies               │  │
│    │  │             properties: name, domain                 │  │
│    │  │  Deal     → /crm/v3/objects/deals                   │  │
│    │  │             properties: dealname, amount, dealstage  │  │
│    │  └─────────────────────────────────────────────────────┘  │
│    │                                                            │
│    │  each type → _fetch_hubspot_objects()                     │
│    │    Authorization: Bearer <access_token>                   │
│    │    limit=100, cursor pagination                           │
│    │                                                            │
│    │  each record → create_integration_item_metadata_object()  │
│    ▼                                                            │
│  IntegrationItem[]  ──────────────────────────────► React UI   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. Pagination

HubSpot CRM endpoints return a maximum of 100 records per request. The integration follows cursor pagination until all records are retrieved:

```text
_fetch_hubspot_objects(access_token, url, properties)
  │
  ├── params = { limit: 100, properties: [...] }
  │
  ▼
  GET {url}?limit=100&properties=...
  │
  ├── extend results with data['results']
  │
  ├── after = data['paging']['next']['after']  ← cursor
  │
  ├── after exists?
  │     │
  │     ├── yes → add after to params, repeat GET
  │     │
  │     └── no  → return all results
  │
  └── non-200 response → stop (other types still load)
```

The `limit=100` is the maximum HubSpot allows per page. The loop continues until `paging.next.after` is absent from the response.

---

## 6. Data Normalization

HubSpot returns provider-specific JSON. Each object is mapped to the shared `IntegrationItem`:

```text
HubSpot API response
  {
    "id": "123",
    "properties": {
      "firstname": "John",
      "lastname":  "Smith",
      "email":     "john@example.com",
      "createdate": "2024-01-15T10:00:00Z",
      "hs_lastmodifieddate": "2024-06-01T08:30:00Z"
    }
  }
        │
        ▼
  create_integration_item_metadata_object(response_json, "Contact")
        │
        ▼
  IntegrationItem
    ├── id                 = "123_Contact"
    ├── type               = "Contact"
    ├── name               = "John Smith"
    ├── creation_time      = "2024-01-15T10:00:00Z"
    └── last_modified_time = "2024-06-01T08:30:00Z"
```

### Name resolution per type

| Type | Primary | Fallback 1 | Fallback 2 |
|---|---|---|---|
| Contact | `firstname + lastname` | `email` | `"Unnamed Contact"` |
| Company | `name` | `domain` | `"Unnamed Company"` |
| Deal | `dealname` | — | `"Unnamed Deal"` |

### ID collision prevention

The `id` is suffixed with the object type (`{hubspot_id}_{type}`) because HubSpot uses independent ID sequences per object type — a Contact and a Company can share the same numeric ID.

---

## 7. Redis Architecture

Redis is not a persistent store here. It serves two purposes only:

### OAuth state (CSRF protection)

```text
Key:   hubspot_state:{org_id}:{user_id}
Value: { "state": "<token>", "user_id": "...", "org_id": "..." }
TTL:   600 seconds
Lifecycle: written on /authorize → validated and deleted on /oauth2callback
```

### Credential handoff

```text
Key:   hubspot_credentials:{org_id}:{user_id}
Value: { "access_token": "...", "refresh_token": "...", "expires_in": 1800 }
TTL:   600 seconds
Lifecycle: written on /oauth2callback → read and deleted on /credentials
```

The client secret is never stored in Redis. Only the tokens returned by HubSpot are stored, and only for the duration of the handoff.

---

## 8. Security

### Secrets management
- All OAuth credentials live in `backend/.env` only — never in source code
- `backend/.env.example` contains placeholders and is safe to commit
- Frontend env (`REACT_APP_*`) holds only the API base URL — no secrets, as `REACT_APP_*` values are exposed in the browser bundle

### OAuth state validation
The state parameter prevents CSRF attacks on the OAuth callback:

```text
/authorize  → generate cryptographic state → store in Redis
/callback   → decode state from URL
            → fetch saved state from Redis
            → compare values
            → mismatch or missing → HTTP 400 rejected
            → match → proceed with token exchange
```

The state is base64-encoded JSON containing `{ state, user_id, org_id }`. This allows the callback to recover the user context from the URL without an extra Redis lookup, while still validating the state value against Redis.

### Scope minimization
Only the minimum read-only scopes are requested:
```text
crm.objects.contacts.read
crm.objects.companies.read
crm.objects.deals.read
```
No write, delete, or admin scopes are requested.

---

## 9. Error Handling

| Situation | Handling |
|---|---|
| User denies OAuth | HubSpot sends `error` param → FastAPI raises HTTP 400 with description |
| State missing from Redis (expired) | HTTP 400 — state does not match |
| State mismatch | HTTP 400 — state does not match |
| Token exchange fails (non-200) | HTTP 400 with HubSpot error text |
| No credentials in Redis on `/credentials` | HTTP 400 — no credentials found |
| HubSpot CRM API non-200 | Loop breaks — that object type returns empty, others still load |
| Empty CRM account | Returns empty `IntegrationItem[]` — not an error |

Sensitive token values are never included in error responses or logs.

---

## 10. Environment Configuration

See `backend/.env.example` for all required backend variables and `frontend/.env.example` for the frontend.

Key backend variables:

| Variable | Purpose |
|---|---|
| `HUBSPOT_CLIENT_ID` | HubSpot OAuth app client ID |
| `HUBSPOT_CLIENT_SECRET` | HubSpot OAuth app client secret |
| `HUBSPOT_REDIRECT_URI` | Must match the redirect URL registered in HubSpot |
| `HUBSPOT_TOKEN_URL` | `https://api.hubapi.com/oauth/2026-03/token` |
| `HUBSPOT_API_BASE_URL` | `https://api.hubapi.com` |
| `FRONTEND_URL` | Used for CORS origin (`http://localhost:3000`) |
| `REDIS_HOST / PORT / DB` | Redis connection |
