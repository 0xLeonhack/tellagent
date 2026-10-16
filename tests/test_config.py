def test_project_env_loader_does_not_override_shell(monkeypatch, tmp_path):
    from tellagent import config

    monkeypatch.setattr(config, "__file__", str(tmp_path / "tellagent" / "config.py"))
    (tmp_path / ".env").write_text("TELLAGENT_TEST_VALUE=from-file\n", encoding="utf-8")
    monkeypatch.setenv("TELLAGENT_TEST_VALUE", "from-shell")
    config.load_project_env()
    assert __import__("os").environ["TELLAGENT_TEST_VALUE"] == "from-shell"
