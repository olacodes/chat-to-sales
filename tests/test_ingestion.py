"""
tests/test_ingestion.py

Tests for the ingestion module:
  - Schema validation
  - Message normalisation
  - POST /api/v1/webhooks/webhook endpoint (event bus mocked)
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.infra.event_bus import Event
from app.modules.ingestion.schemas import Channel, InboundMessageRequest
from app.modules.ingestion.service import IngestionService, MESSAGE_RECEIVED_EVENT


# ── Schema validation ─────────────────────────────────────────────────────────


def test_valid_inbound_message_parses():
    req = InboundMessageRequest(
        channel="whatsapp",
        sender="+2348012345678",
        message="I want 2 shoes",
        tenant_id="tenant-001",
    )
    assert req.channel == Channel.WHATSAPP
    assert req.message == "I want 2 shoes"


def test_channel_is_normalised_to_lowercase():
    req = InboundMessageRequest(
        channel="WhatsApp",
        sender="+2348012345678",
        message="Hello",
        tenant_id="t1",
    )
    assert req.channel == Channel.WHATSAPP


def test_message_is_stripped():
    req = InboundMessageRequest(
        channel="whatsapp",
        sender="+2348012345678",
        message="  Hello world  ",
        tenant_id="t1",
    )
    assert req.message == "Hello world"


def test_empty_message_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InboundMessageRequest(
            channel="whatsapp",
            sender="+2348012345678",
            message="   ",  # becomes empty after strip — min_length=1 fails
            tenant_id="t1",
        )


def test_missing_tenant_id_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InboundMessageRequest(
            channel="whatsapp",
            sender="+2348012345678",
            message="Hello",
            tenant_id="",  # empty string — min_length=1
        )


def test_invalid_channel_rejected():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        InboundMessageRequest(
            channel="telegram",
            sender="+2348012345678",
            message="Hello",
            tenant_id="t1",
        )


# ── Normalisation ─────────────────────────────────────────────────────────────


def test_normalize_produces_lowercase_and_word_count():
    req = InboundMessageRequest(
        channel="whatsapp",
        sender="+2348012345678",
        message="I Want 2 Shoes Please",
        tenant_id="t1",
    )
    result = IngestionService.normalize(req)
    assert result.message_lower == "i want 2 shoes please"
    assert result.word_count == 5
    assert result.is_empty is False


def test_normalize_single_word():
    req = InboundMessageRequest(
        channel="whatsapp",
        sender="+2348012345678",
        message="Hello",
        tenant_id="t1",
    )
    result = IngestionService.normalize(req)
    assert result.word_count == 1


def test_normalize_preserves_tenant_and_channel():
    req = InboundMessageRequest(
        channel="sms",
        sender="+2348099999999",
        message="Order milk",
        tenant_id="tenant-xyz",
    )
    result = IngestionService.normalize(req)
    assert result.tenant_id == "tenant-xyz"
    assert result.channel == Channel.SMS


# ── Service process() ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_process_publishes_message_received_event():
    req = InboundMessageRequest(
        channel="whatsapp",
        sender="+2348012345678",
        message="I want 2 shoes",
        tenant_id="tenant-abc",
    )

    captured: list[Event] = []

    def capture_publish(event: Event) -> int:
        captured.append(event)
        return 1

    with patch(
        "app.modules.ingestion.service.publish_event", side_effect=capture_publish
    ):
        svc = IngestionService()
        normalized = await svc.process(req)

    assert len(captured) == 1
    evt = captured[0]
    assert evt.event_name == MESSAGE_RECEIVED_EVENT
    assert evt.tenant_id == "tenant-abc"
    assert evt.payload["sender"] == "+2348012345678"
    assert evt.payload["channel"] == "whatsapp"
    assert normalized.word_count == 4


# ── HTTP endpoint ─────────────────────────────────────────────────────────────


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


def test_post_webhook_returns_202(client: TestClient):
    def mock_publish(event: Event) -> int:
        return 1

    with patch("app.modules.ingestion.service.publish_event", side_effect=mock_publish):
        response = client.post(
            "/api/v1/webhooks/webhook",
            json={
                "channel": "whatsapp",
                "sender": "+2348012345678",
                "message": "I want 2 shoes",
                "tenant_id": "tenant-001",
            },
        )
    assert response.status_code == 202
    body = response.json()
    assert body["channel"] == "whatsapp"
    assert body["word_count"] == 4
    assert body["message_lower"] == "i want 2 shoes"


def test_post_webhook_rejects_empty_message(client: TestClient):
    response = client.post(
        "/api/v1/webhooks/webhook",
        json={
            "channel": "whatsapp",
            "sender": "+2348012345678",
            "message": "",
            "tenant_id": "tenant-001",
        },
    )
    assert response.status_code == 422


def test_post_webhook_rejects_unknown_channel(client: TestClient):
    response = client.post(
        "/api/v1/webhooks/webhook",
        json={
            "channel": "telegram",
            "sender": "+2348012345678",
            "message": "hello",
            "tenant_id": "tenant-001",
        },
    )
    assert response.status_code == 422
