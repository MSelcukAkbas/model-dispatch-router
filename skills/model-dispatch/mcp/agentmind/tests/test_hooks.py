import json

from agentmind.hooks import install_hooks


def test_installer_merges_codex_and_claude_hooks(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps({"permissions": {"allow": ["Read"]}, "hooks": {"Stop": []}}),
        encoding="utf-8",
    )

    written = install_hooks(tmp_path, "all")

    assert set(written) == {
        tmp_path / ".codex" / "hooks.json",
        tmp_path / ".claude" / "settings.json",
    }
    claude = json.loads(settings.read_text(encoding="utf-8"))
    assert claude["permissions"] == {"allow": ["Read"]}
    assert claude["hooks"]["Stop"] == []
    assert claude["hooks"]["SessionStart"][0]["hooks"][0]["command"] == (
        "agentmind-hook start"
    )


def test_installer_is_idempotent(tmp_path):
    install_hooks(tmp_path, "codex")
    install_hooks(tmp_path, "codex")

    document = json.loads(
        (tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8")
    )
    assert len(document["hooks"]["SessionStart"]) == 1
    assert len(document["hooks"]["SessionEnd"]) == 1
