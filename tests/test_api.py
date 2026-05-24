from fastapi.testclient import TestClient

from server import main


def test_new_game_allows_missing_provider_keys(monkeypatch):
    for env_name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DASHSCOPE_API_KEY"):
        monkeypatch.delenv(env_name, raising=False)

    client = TestClient(main.app)
    res = client.post(
        "/api/new-game",
        json={"ai_characters": ["claude", "gpt"], "output_language": "zh"},
    )

    assert res.status_code == 200
    data = res.json()
    assert [p["character_id"] for p in data["players"][1:]] == ["claude", "gpt"]
