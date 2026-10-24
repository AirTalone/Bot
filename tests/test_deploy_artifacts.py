from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prod_compose_alias_exists() -> None:
    prod = ROOT / "compose.prod.yml"
    assert prod.exists()
    text = prod.read_text(encoding="utf-8") if prod.is_file() and not prod.is_symlink() else (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" in text
    assert "ports:" not in text.split("db:")[1].split("migrate:")[0] or "ports: []" in text
    # Prod db service must not publish host ports.
    db_block = text.split("db:")[1].split("migrate:")[0]
    assert "5432:5432" not in db_block


def test_deploy_kit_files_present() -> None:
    required = [
        "docs/DEPLOY.md",
        "docs/GO_LIVE.md",
        "deploy/env.prod.example",
        "deploy/vpnbot.service",
        "deploy/ufw-setup.sh",
        "deploy/Caddyfile.example",
        "scripts/deploy_prod.sh",
        "scripts/backup_postgres.sh",
    ]
    for rel in required:
        path = ROOT / rel
        assert path.is_file(), rel
        assert path.stat().st_size > 20, rel


def test_gitignore_keeps_secrets_and_backups_out() -> None:
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for token in (".env", ".env.prod", "backups/", "*.sql.gz"):
        assert token in ignore


def test_deploy_doc_has_fifteen_commands_section() -> None:
    body = (ROOT / "docs/DEPLOY.md").read_text(encoding="utf-8")
    assert "15 команд" in body
    assert "compose.prod.yml" in body
    assert "ufw-setup.sh" in body
