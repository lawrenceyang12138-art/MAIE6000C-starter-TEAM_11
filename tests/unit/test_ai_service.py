from services.ai.app.main import triage_text


def test_triage_access_case():
    result = triage_text(
        "Cannot login",
        "User cannot access the dashboard after a password reset.",
    )
    assert result.label == "access"
    assert result.confidence >= 0.55
    assert "Cannot login" in result.summary


def test_triage_general_case():
    result = triage_text(
        "General question",
        "Need clarification about the process for next week.",
    )
    assert result.label == "general"
