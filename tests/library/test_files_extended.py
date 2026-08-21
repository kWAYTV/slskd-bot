"""Extended tests for file_handler edge cases."""

from music_downloader.library.files import FileProcessor


class TestFindDownloadedFileFallback:
    def test_fallback_search(self, tmp_path):
        download_dir = tmp_path / "downloads"
        output_dir = tmp_path / "output"
        download_dir.mkdir()
        output_dir.mkdir()
        # File under a different username directory
        other_dir = download_dir / "otheruser" / "subdir"
        other_dir.mkdir(parents=True)
        (other_dir / "song.flac").write_text("data")

        processor = FileProcessor(str(download_dir), str(output_dir))
        # Search with wrong username should still find via fallback
        result = processor.find_downloaded_file("wronguser", "\\Music\\song.flac")
        assert result is not None
        assert result.endswith("song.flac")


class TestProcessFileEdgeCases:
    def test_process_nonexistent_file(self, tmp_path):
        download_dir = tmp_path / "downloads"
        output_dir = tmp_path / "output"
        download_dir.mkdir()
        output_dir.mkdir()
        processor = FileProcessor(str(download_dir), str(output_dir))
        result = processor.process_file("/nonexistent/file.flac", "Artist", "Title")
        assert result is None

    def test_process_file_no_extension(self, tmp_path):
        download_dir = tmp_path / "downloads"
        output_dir = tmp_path / "output"
        download_dir.mkdir()
        output_dir.mkdir()
        source = tmp_path / "sourcefile"
        source.write_text("data")
        processor = FileProcessor(str(download_dir), str(output_dir))
        result = processor.process_file(str(source), "Artist", "Title")
        assert result is not None


class TestCleanupDownload:
    def test_cleanup_removes_empty_parent(self, tmp_path):
        download_dir = tmp_path / "downloads"
        output_dir = tmp_path / "output"
        download_dir.mkdir()
        output_dir.mkdir()
        parent = tmp_path / "downloads" / "user" / "subdir"
        parent.mkdir(parents=True)
        source = parent / "song.flac"
        source.write_text("data")
        processor = FileProcessor(str(download_dir), str(output_dir))
        processor.cleanup_download(str(source))
        assert not source.exists()
        assert not parent.exists()

    def test_cleanup_nonexistent(self, tmp_path):
        download_dir = tmp_path / "downloads"
        output_dir = tmp_path / "output"
        download_dir.mkdir()
        output_dir.mkdir()
        processor = FileProcessor(str(download_dir), str(output_dir))
        result = processor.cleanup_download("/nonexistent/file.flac")
        assert result is False

    def test_build_filename_custom_template(self, tmp_path):
        download_dir = tmp_path / "downloads"
        output_dir = tmp_path / "output"
        download_dir.mkdir()
        output_dir.mkdir()
        processor = FileProcessor(str(download_dir), str(output_dir), filename_template="{title} by {artist}")
        result = processor.build_filename("Artist", "Song", "mp3")
        assert result == "Song by Artist.mp3"
