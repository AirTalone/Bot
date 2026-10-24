from pathlib import Path


def test_alembic_files_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "alembic.ini").is_file()
    assert (root / "alembic" / "env.py").is_file()
    versions = list((root / "alembic" / "versions").glob("*.py"))
    assert versions, "expected at least one alembic revision"


def test_dockerfile_and_compose_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "Dockerfile").is_file()
    assert (root / "docker-compose.yml").is_file()
    assert (root / ".github" / "workflows" / "ci.yml").is_file()
