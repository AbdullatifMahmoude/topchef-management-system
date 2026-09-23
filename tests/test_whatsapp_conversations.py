from app.modules.settings.whatsapp import normalize_whatsapp_phone
from app.modules.settings.whatsapp_conversations import (
    _message_content,
    _normalize_intent_text,
)


def test_phone_formats_normalize_to_same_whatsapp_identity():
    expected = "201012345678"
    assert normalize_whatsapp_phone("01012345678") == expected
    assert normalize_whatsapp_phone("+20 10 1234 5678") == expected
    assert normalize_whatsapp_phone("201012345678") == expected


def test_conversation_router_reads_text_and_interactive_payloads():
    assert _message_content({"type": "text", "text": {"body": " عاوز استلم تحديثات "}}) == (
        "عاوز استلم تحديثات", "",
    )
    assert _message_content({
        "type": "interactive",
        "interactive": {"list_reply": {"id": "ENABLE_ORDER:42", "title": "طلب #42"}},
    }) == ("طلب #42", "ENABLE_ORDER:42")


def test_arabic_intent_normalization_handles_hamza_and_taa_marbuta():
    assert _normalize_intent_text(" عاوز أتابع خدمة العملاء ") == "عاوز اتابع خدمه العملاء"
