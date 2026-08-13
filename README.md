# Pipeline – HubSpot Integration

## Overview

Pipeline is an integration platform that connects SaaS applications such as HubSpot, Airtable, and Notion so data can be accessed and used in automated workflows.

This project adds a complete **HubSpot OAuth + CRM data integration** to the existing Pipeline application alongside the Airtable and Notion integrations.

### What it does

1. Connects a user to HubSpot through OAuth 2.0.
2. Uses Redis for short-lived OAuth state and credential handoff.
3. Exchanges the HubSpot authorization code for access/refresh tokens.
4. Retrieves HubSpot CRM data for:
   - Contacts
   - Companies
   - Deals
5. Handles HubSpot cursor pagination.
6. Converts HubSpot records into the common `IntegrationItem` model.
7. Displays the normalized data in the React frontend.

---

## Technology Stack

| Layer | Technology | Purpose |
|---|---|---|
| Frontend | React | Integration UI and data display |
| UI | Material UI | Form controls and layout |
| HTTP client | Axios | Frontend → FastAPI requests |
| Backend | FastAPI | OAuth callbacks and integration API |
| Language | Python | Backend implementation |
| External API | HubSpot CRM API | Contacts, Companies, Deals |
| Authentication | OAuth 2.0 | Secure HubSpot authorization |
| Temporary storage | Redis | OAuth state and short-lived credentials |
| Async HTTP | HTTPX | Backend → HubSpot requests |
| Data model | `IntegrationItem` | Provider-independent normalized item format |

---

## Project Structure

```text
pipeline/
│
├── README.md
├── ARCHITECTURE.md
├── .gitignore
│
├── backend/
│   ├── .env                 # local only; never commit
│   ├── .env.example
│   ├── .gitignore
│   ├── main.py
│   ├── redis_client.py
│   ├── requirements.txt
│   │
│   └── integrations/
│       ├── airtable.py
│       ├── notion.py
│       ├── hubspot.py
│       └── integration_item.py
│
└── frontend/
    ├── .env                 # local only; never commit
    ├── .env.example
    ├── .gitignore
    ├── package.json
    ├── package-lock.json
    │
    └── src/
        ├── App.js
        ├── integration-form.js
        ├── data-form.js
        └── integrations/
            ├── airtable.js
            ├── notion.js
            └── hubspot.js
```

---

# Local Setup

## 1. Prerequisites

- Node.js 20+
- npm
- Python 3.10+
- Docker Desktop
- A HubSpot developer account
- A HubSpot developer test account (for sample Contacts, Companies, and Deals)

---

## 2. Start Redis with Docker

```bash
docker run -d --name pipeline-redis -p 6379:6379 redis:7-alpine
```

Verify:

```bash
docker ps
```

---

# Backend Setup

## 3. Create Python environment

From the `backend` directory:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 4. Configure backend environment variables

Copy `backend/.env.example` to `backend/.env` and fill in your values.

---

## 5. Start FastAPI

```powershell
uvicorn main:app --reload --port 8000
```

Health check:

```text
GET http://localhost:8000/
→ {"Ping":"Pong"}
```

---

# Frontend Setup

## 6. Install dependencies

```powershell
npm install
```

---

## 7. Configure frontend environment

Create `frontend/.env`:

```env
REACT_APP_API_BASE_URL=http://localhost:8000
```

Do **not** put HubSpot client secrets in frontend environment variables — `REACT_APP_*` values are exposed to browser code.

---

## 8. Start React

```powershell
npm start
```

Opens at `http://localhost:3000`.

---

# HubSpot Developer Setup

## 9. Create a HubSpot developer account

Go to `https://developers.hubspot.com/` and create a developer account and a developer test account for sample CRM data.

---

## 10. Install and authenticate the HubSpot CLI

```powershell
npm install -g @hubspot/cli
hs --version
hs account auth
```

---

## 11. Create the HubSpot project

```powershell
mkdir C:\Users\<username>\Documents\hubspot-projects
cd C:\Users\<username>\Documents\hubspot-projects
hs project create
```

Choices:

```text
Project base:       App
Distribution:       Privately
Authentication:     OAuth
Features:           None
```

---

## 12. Configure OAuth in `app-hsmeta.json`

```json
{
  "auth": {
    "type": "oauth",
    "redirectUrls": [
      "http://localhost:8000/integrations/hubspot/oauth2callback"
    ],
    "requiredScopes": [
      "oauth",
      "crm.objects.contacts.read",
      "crm.objects.companies.read",
      "crm.objects.deals.read"
    ]
  }
}
```

Also permit `https://api.hubapi.com` for API fetches.

---

## 13. Upload and deploy

```powershell
hs project upload
```

Answer `Y` if asked to create the project. On success the build output provides the OAuth Client ID and Client Secret — add these to `backend/.env`.

---

# HubSpot OAuth Flow

```text
React
  ↓
POST /integrations/hubspot/authorize
  ↓
FastAPI generates OAuth state → Redis
  ↓
HubSpot authorization URL
  ↓
User authorizes
  ↓
HubSpot redirects to FastAPI callback
  ↓
FastAPI validates state, exchanges code for tokens
  ↓
Redis stores short-lived credentials
  ↓
Popup closes
```

Token endpoint used:

```text
https://api.hubapi.com/oauth/2026-03/token
```

---

# Application API

| Method | Route | Purpose |
|---|---|---|
| POST | `/integrations/hubspot/authorize` | Starts OAuth |
| GET | `/integrations/hubspot/oauth2callback` | Receives OAuth callback |
| POST | `/integrations/hubspot/credentials` | Retrieves temporary OAuth credentials |
| POST | `/integrations/hubspot/load` | Loads Contacts, Companies and Deals |

---

# HubSpot Data Flow

After authorization the backend calls the HubSpot CRM APIs using a Bearer access token, loads Contacts, Companies, and Deals, and normalizes each record into `IntegrationItem`:

```text
IntegrationItem
├── id
├── type
├── name
├── creation_time
└── last_modified_time
```

Cursor pagination via `paging.next.after` ensures all pages are retrieved.

---

# Testing

## Functional

1. Start Redis, FastAPI, and React.
2. Select `HubSpot` and click `Connect`.
3. Complete HubSpot OAuth.
4. Click `Load Data`.
5. Verify Contacts, Companies, and Deals appear.

## Backend only

```powershell
curl.exe -X POST "http://localhost:8000/integrations/hubspot/authorize" `
  -F "user_id=test-user" `
  -F "org_id=test-org"
```

Returns a HubSpot authorization URL.

Do not paste OAuth URLs or tokens into public logs or source control.
