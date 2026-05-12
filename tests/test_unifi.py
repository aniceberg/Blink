from app.models import Settings
from app.services.unifi import UniFiClient


def test_private_headers_do_not_send_integration_api_key():
    client = UniFiClient(
        Settings(
            id=1,
            host="https://unifi.local",
            api_key="integration-key",
            username="local-user",
            password="local-pass",
            verify_ssl=False,
            timezone="America/New_York",
            output_dir="data/media",
        )
    )

    assert client._headers()["X-API-KEY"] == "integration-key"
    assert "X-API-KEY" not in client._private_headers("image/jpeg")
