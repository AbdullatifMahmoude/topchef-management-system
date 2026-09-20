from app.modules.settings.whatsapp_webhook import webhook_events


def test_webhook_events_reads_regular_messages():
    message = {"id": "wamid.regular"}

    assert webhook_events({"messages": [message]}, "messages") == [message]


def test_webhook_events_reads_business_agent_standby_messages():
    message = {"id": "wamid.standby"}

    assert webhook_events({"standby": {"messages": [message]}}, "messages") == [message]


def test_webhook_events_combines_regular_and_standby_statuses():
    regular = {"id": "wamid.regular", "status": "sent"}
    standby = {"id": "wamid.standby", "status": "delivered"}

    assert webhook_events(
        {"statuses": [regular], "standby": {"statuses": [standby]}},
        "statuses",
    ) == [regular, standby]
