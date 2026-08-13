# Pipeline – HubSpot Integration: Implementation Approach

## What Was Built

A complete HubSpot OAuth 2.0 + CRM data integration added to the existing Pipeline application, following the same pattern as the Airtable and Notion integrations already present in the codebase.

The integration covers:
- HubSpot OAuth authorization via a popup window
- Token exchange and short-lived credential handoff through Redis
- Loading Contacts, Companies, and Deals from the HubSpot CRM API
- Cursor pagination to retrieve all records beyond the first page
- Normalization of HubSpot records into the shared `IntegrationItem` model
- Display of normalized data in the React frontend

---

## Approach

### Followed the existing pattern

The codebase already had working Airtable and Notion integrations. Rather than inventing a new structure, the HubSpot integration follows the same contract:

- A provider file `integrations/hubspot.py` handles all HubSpot-specific logic
- Four thin FastAPI routes in `main.py` delegate to it
- A React component `src/integrations/hubspot.js` handles the frontend OAuth flow
- `data-form.js` handles data loading — HubSpot was registered alongside the existing providers with no changes to the shared component

### OAuth state via Redis

HubSpot's OAuth callback arrives at the backend without a session. To securely link the callback to the original request, a cryptographic state token is generated, base64-encoded with `user_id` and `org_id`, and stored in Redis with a 600s TTL. On callback, the state is decoded, looked up in Redis, and compared — mismatches are rejected.

After a successful token exchange, the credentials are placed in Redis under a separate key. The popup closes via `window.close()`, the frontend detects this by polling, then calls `/credentials` to retrieve and consume the tokens. The key is deleted immediately after.

### CRM data loading

After authorization, the backend fetches Contacts, Companies, and Deals using the stored `access_token` as a Bearer token. Each object type is fetched from its own CRM v3 endpoint with the specific properties needed for normalization.

Cursor pagination is handled in `_fetch_hubspot_objects()` — it requests 100 records per page and follows `paging.next.after` until no cursor is returned. This ensures all records are retrieved regardless of account size.

### Normalization

Each HubSpot object is converted to `IntegrationItem` in `create_integration_item_metadata_object()`. Name resolution handles each type differently:

- Contact → `firstname + lastname`, falls back to `email`, then `"Unnamed Contact"`
- Company → `name`, falls back to `domain`, then `"Unnamed Company"`
- Deal → `dealname`, falls back to `"Unnamed Deal"`

The `id` field is suffixed with the type (`123_Contact`) to avoid collisions across object types.

### Environment variables

All secrets (`CLIENT_ID`, `CLIENT_SECRET`, `REDIRECT_URI`, `TOKEN_URL`, `API_BASE_URL`) are read from environment variables. The `AUTHORIZATION_URL` is built at module load time from these values. `backend/.env.example` provides the template.

---

## Key Files

| File | Role |
|---|---|
| `backend/integrations/hubspot.py` | OAuth logic, CRM fetching, pagination, normalization |
| `backend/main.py` | Thin FastAPI route registration |
| `backend/redis_client.py` | Redis helpers used for state and credential handoff |
| `frontend/src/integrations/hubspot.js` | Connect button, popup handling, credential retrieval |
| `frontend/src/data-form.js` | Load Data button, displays `IntegrationItem[]` |

---

## Decisions and Trade-offs

**Redis for credential handoff instead of a session or database**
The credentials only need to survive the few seconds between the OAuth callback closing the popup and the frontend calling `/credentials`. Redis with a short TTL is the right tool — no persistent storage needed, and the key is deleted on consumption.

**Synchronous `requests` for CRM fetching**
The pagination loop in `_fetch_hubspot_objects()` is synchronous. This keeps the pagination logic simple and readable. The function is called from an async context but does not block the event loop in a meaningful way for this use case.

**State encoded as base64 JSON in the URL**
HubSpot passes the `state` parameter back through the redirect URL. Encoding the full `{state, user_id, org_id}` payload as base64 avoids a Redis lookup just to recover the user context — the callback can decode it directly and then validate the state value against Redis.

**No token refresh implemented**
The integration uses the `access_token` directly. Tokens expire after 30 minutes. For this use case (load data immediately after connecting), this is sufficient. A production implementation would use the `refresh_token` to obtain a new `access_token` when needed.

---

## How to Verify It Works

1. Start Redis, FastAPI, and React (see README).
2. Select `HubSpot` from the integration dropdown.
3. Click `Connect to HubSpot` — a HubSpot authorization popup opens.
4. Authorize the app — the popup closes automatically.
5. The button changes to `HubSpot Connected`.
6. Click `Load Data` — Contacts, Companies, and Deals appear as normalized JSON in the text area.
