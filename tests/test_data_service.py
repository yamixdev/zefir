from pathlib import Path

import pytest

from bot.services.data_service import data_path


def test_game_data_files_are_available_from_repo_root():
    assert data_path("hangman_words_ru.json").exists()
    assert data_path("quiz_questions.json").exists()


def test_game_data_files_are_available_from_src_cwd(monkeypatch):
    src_dir = Path.cwd() / "src"
    if not src_dir.exists():
        pytest.skip("src directory is not available")
    monkeypatch.chdir(src_dir)

    assert data_path("hangman_words_ru.json").exists()
    assert data_path("quiz_questions.json").exists()
