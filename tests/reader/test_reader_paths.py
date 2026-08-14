from apps.reader.paths import reader_paths


def test_reader_paths_use_docxtool_home_without_creating_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCXTOOL_HOME", str(tmp_path / "home"))

    paths = reader_paths()

    assert paths.root == tmp_path / "home" / "reader"
    assert paths.books_dir == paths.root / "books"
    assert paths.database_path == paths.root / "reader.db"
    assert not paths.root.exists()


def test_reader_paths_create_only_managed_directories(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCXTOOL_HOME", str(tmp_path / "home"))
    paths = reader_paths()

    paths.ensure_directories()

    assert paths.books_dir.is_dir()
    assert paths.temp_dir.is_dir()
    assert not paths.database_path.exists()
