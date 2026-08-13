import os
from dotenv import load_dotenv
import json
import secrets
from fastapi import Request, HTTPException
from fastapi.responses import HTMLResponse
import httpx
import asyncio
import base64
import requests

from integrations.integration_item import IntegrationItem
from redis_client import add_key_value_redis, get_value_redis, delete_key_redis

load_dotenv()

# hubSpot OAuth configuration
# 1. create a developer app at https://developers.hubspot.com/
# 2. under Auth, set the redirect URL to REDIRECT_URI below.
# 3. under Auth, add the scopes listed in SCOPES below.
# 4. copy the app Client ID and Client Secret into the two constants below.

CLIENT_ID = os.getenv("HUBSPOT_CLIENT_ID")
CLIENT_SECRET = os.getenv("HUBSPOT_CLIENT_SECRET")
REDIRECT_URI = os.getenv(
    "HUBSPOT_REDIRECT_URI",
    "http://localhost:8000/integrations/hubspot/oauth2callback"
)

# These scopes must also be enabled in the HubSpot app's "Auth" settings,
# otherwise HubSpot rejects the authorization request.
SCOPES = 'crm.objects.contacts.read crm.objects.companies.read crm.objects.deals.read'

AUTHORIZATION_URL = (
    'https://app.hubspot.com/oauth/authorize'
    f'?client_id={CLIENT_ID}'
    f'&redirect_uri={REDIRECT_URI}'
    f'&scope={SCOPES.replace(" ", "%20")}'
)
TOKEN_URL = os.getenv("HUBSPOT_TOKEN_URL")
API_BASE_URL = os.getenv("HUBSPOT_API_BASE_URL", "https://api.hubapi.com")


async def authorize_hubspot(user_id, org_id):
    """Build the HubSpot authorization URL and stash a CSRF state token in Redis."""
    state_data = {
        'state': secrets.token_urlsafe(32),
        'user_id': user_id,
        'org_id': org_id,
    }
    # base64-url-encode so the JSON survives being passed through the URL
    encoded_state = base64.urlsafe_b64encode(
        json.dumps(state_data).encode('utf-8')
    ).decode('utf-8')

    await add_key_value_redis(
        f'hubspot_state:{org_id}:{user_id}',
        json.dumps(state_data),
        expire=600,
    )

    return f'{AUTHORIZATION_URL}&state={encoded_state}'


async def oauth2callback_hubspot(request: Request):
    """Handle HubSpot's redirect: validate state, exchange the code for tokens."""
    if request.query_params.get('error'):
        raise HTTPException(
            status_code=400,
            detail=request.query_params.get('error_description')
            or request.query_params.get('error'),
        )

    code = request.query_params.get('code')
    encoded_state = request.query_params.get('state')
    state_data = json.loads(base64.urlsafe_b64decode(encoded_state).decode('utf-8'))

    original_state = state_data.get('state')
    user_id = state_data.get('user_id')
    org_id = state_data.get('org_id')

    saved_state = await get_value_redis(f'hubspot_state:{org_id}:{user_id}')

    if not saved_state or original_state != json.loads(saved_state).get('state'):
        raise HTTPException(status_code=400, detail='State does not match.')

    async with httpx.AsyncClient() as client:
        response, _ = await asyncio.gather(
            client.post(
                TOKEN_URL,
                data={
                    'grant_type': 'authorization_code',
                    'client_id': CLIENT_ID,
                    'client_secret': CLIENT_SECRET,
                    'redirect_uri': REDIRECT_URI,
                    'code': code,
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
            ),
            delete_key_redis(f'hubspot_state:{org_id}:{user_id}'),
        )

    if response.status_code != 200:
        raise HTTPException(status_code=400, detail=f'Token exchange failed: {response.text}')

    await add_key_value_redis(
        f'hubspot_credentials:{org_id}:{user_id}',
        json.dumps(response.json()),
        expire=600,
    )

    close_window_script = """
    <html>
        <script>
            window.close();
        </script>
    </html>
    """
    return HTMLResponse(content=close_window_script)


async def get_hubspot_credentials(user_id, org_id):
    """Read (and clear) the stored HubSpot credentials for this user/org."""
    credentials = await get_value_redis(f'hubspot_credentials:{org_id}:{user_id}')
    if not credentials:
        raise HTTPException(status_code=400, detail='No credentials found.')
    credentials = json.loads(credentials)
    await delete_key_redis(f'hubspot_credentials:{org_id}:{user_id}')

    return credentials


# Phase 3 — loading HubSpot CRM objects as IntegrationItems

def create_integration_item_metadata_object(response_json, item_type) -> IntegrationItem:
    """Map a single HubSpot CRM object into our normalized IntegrationItem."""
    properties = response_json.get('properties', {}) or {}

    # Pick a human-readable name depending on which object type this is.
    if item_type == 'Contact':
        first = properties.get('firstname') or ''
        last = properties.get('lastname') or ''
        name = f'{first} {last}'.strip() or properties.get('email') or 'Unnamed Contact'
    elif item_type == 'Company':
        name = properties.get('name') or properties.get('domain') or 'Unnamed Company'
    elif item_type == 'Deal':
        name = properties.get('dealname') or 'Unnamed Deal'
    else:
        name = properties.get('name') or 'Unnamed'

    return IntegrationItem(
        id=f"{response_json.get('id')}_{item_type}",
        type=item_type,
        name=name,
        creation_time=properties.get('createdate') or response_json.get('createdAt'),
        last_modified_time=properties.get('hs_lastmodifieddate') or response_json.get('updatedAt'),
    )


def _fetch_hubspot_objects(access_token, url, properties):
    """Fetch every object of one CRM type, following HubSpot's cursor pagination."""
    results = []
    after = None
    while True:
        params = {'limit': 100, 'properties': properties}
        if after:
            params['after'] = after

        response = requests.get(
            url,
            headers={'Authorization': f'Bearer {access_token}'},
            params=params,
        )
        if response.status_code != 200:
            # Stop on error (e.g. a scope the app wasn't granted); other types still load.
            break

        data = response.json()
        results.extend(data.get('results', []))

        after = data.get('paging', {}).get('next', {}).get('after')
        if not after:
            break

    return results


async def get_items_hubspot(credentials):
    """Query HubSpot CRM (contacts, companies, deals) and return IntegrationItems."""
    credentials = json.loads(credentials)
    access_token = credentials.get('access_token')

    # (display type, endpoint, properties to request)
    object_types = [
        ('Contact', f'{API_BASE_URL}/crm/v3/objects/contacts', ['firstname', 'lastname', 'email']),
        ('Company', f'{API_BASE_URL}/crm/v3/objects/companies', ['name', 'domain']),
        ('Deal', f'{API_BASE_URL}/crm/v3/objects/deals', ['dealname', 'amount', 'dealstage']),
    ]

    list_of_integration_item_metadata = []
    for item_type, url, properties in object_types:
        for obj in _fetch_hubspot_objects(access_token, url, properties):
            list_of_integration_item_metadata.append(
                create_integration_item_metadata_object(obj, item_type)
            )

    print(f'list_of_integration_item_metadata: {list_of_integration_item_metadata}')
    return list_of_integration_item_metadata
