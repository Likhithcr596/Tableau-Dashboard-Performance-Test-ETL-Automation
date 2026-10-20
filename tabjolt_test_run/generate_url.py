import requests
import xml.etree.ElementTree as ET

# Dummy Tableau Server configuration
SERVER_URL = "https://tableau.example.com"
API_VERSION = "3.10"
USERNAME = "demo_user"
PASSWORD = "dummy_password"
SITE_NAME = "demo_site"

# Common headers
headers = {
    "Accept": "application/xml",
    "Content-Type": "application/json"
}

TABLEAU_NAMESPACE = "{http://tableau.com/api}"


# Authenticate and retrieve the authentication token
def authenticate():
    url = f"{SERVER_URL}/api/{API_VERSION}/auth/signin"

    payload = {
        "credentials": {
            "name": USERNAME,
            "password": PASSWORD,
            "site": {
                "contentUrl": SITE_NAME
            }
        }
    }

    response = requests.post(
        url,
        json=payload,
        headers=headers,
        timeout=30
    )

    if response.status_code != 200:
        print(
            f"Authentication failed. "
            f"Status code: {response.status_code}"
        )
        response.raise_for_status()

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as e:
        print(f"Failed to parse authentication response: {e}")
        raise

    credentials = root.find(
        f".//{TABLEAU_NAMESPACE}credentials"
    )
    site = root.find(f".//{TABLEAU_NAMESPACE}site")

    if credentials is None or site is None:
        raise ValueError(
            "Authentication response is missing credentials or site."
        )

    auth_token = credentials.get("token")
    site_id = site.get("id")

    if not auth_token or not site_id:
        raise ValueError(
            "Authentication token or site ID is missing."
        )

    return auth_token, site_id


# Retrieve all workbooks for the site
def get_workbooks(auth_token, site_id):
    url = (
        f"{SERVER_URL}/api/{API_VERSION}"
        f"/sites/{site_id}/workbooks"
    )

    auth_headers = headers.copy()
    auth_headers["X-Tableau-Auth"] = auth_token

    response = requests.get(
        url,
        headers=auth_headers,
        timeout=30
    )

    if response.status_code != 200:
        print(
            f"Failed to retrieve workbooks. "
            f"Status code: {response.status_code}"
        )
        response.raise_for_status()

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as e:
        print(f"Failed to parse workbook response: {e}")
        raise

    return root.findall(
        f".//{TABLEAU_NAMESPACE}workbook"
    )


# Retrieve all views for a workbook
def get_views(auth_token, site_id, workbook_id):
    url = (
        f"{SERVER_URL}/api/{API_VERSION}"
        f"/sites/{site_id}/workbooks/{workbook_id}/views"
    )

    auth_headers = headers.copy()
    auth_headers["X-Tableau-Auth"] = auth_token

    response = requests.get(
        url,
        headers=auth_headers,
        timeout=30
    )

    if response.status_code != 200:
        print(
            f"Failed to retrieve views for workbook "
            f"{workbook_id}. Status code: {response.status_code}"
        )
        response.raise_for_status()

    try:
        root = ET.fromstring(response.text)
    except ET.ParseError as e:
        print(f"Failed to parse views response: {e}")
        raise

    return root.findall(
        f".//{TABLEAU_NAMESPACE}view"
    )


# Retrieve view URLs for all workbooks on the site
def get_all_view_urls_from_site():
    auth_token, site_id = authenticate()

    try:
        workbooks = get_workbooks(auth_token, site_id)
        all_view_urls = []

        for workbook in workbooks:
            workbook_id = workbook.get("id")

            if not workbook_id:
                continue

            views = get_views(
                auth_token,
                site_id,
                workbook_id
            )

            for view in views:
                content_url = view.get("contentUrl")

                if content_url:
                    view_url = (
                        f"{SERVER_URL}/t/{SITE_NAME}"
                        f"/views/{content_url}"
                    )
                    all_view_urls.append(view_url)

        return all_view_urls

    finally:
        # Sign out to invalidate the authentication session
        signout_url = (
            f"{SERVER_URL}/api/{API_VERSION}/auth/signout"
        )
        auth_headers = headers.copy()
        auth_headers["X-Tableau-Auth"] = auth_token

        try:
            requests.post(
                signout_url,
                headers=auth_headers,
                timeout=15
            )
        except requests.exceptions.RequestException:
            print("Warning: Tableau sign-out request failed.")


# Run the script
if __name__ == "__main__":
    try:
        view_urls = get_all_view_urls_from_site()

        for url in view_urls:
            print(url)

    except requests.exceptions.RequestException as e:
        print(f"Tableau API request failed: {e}")

    except (ET.ParseError, ValueError) as e:
        print(f"Failed to process Tableau response: {e}")
