"""Rename and place downloaded files in the music library."""

import contextlib
import logging
import os
import re
import shutil
from difflib import SequenceMatcher

import mutagen.flac

logger = logging.getLogger(__name__)

_AUDIO_EXTENSIONS = {".flac", ".alac", ".wav", ".aiff", ".mp3", ".aac", ".m4a", ".ogg", ".opus", ".wma"}


class FileProcessor:
    """Handles file renaming, moving, and cleanup."""

    def __init__(self, download_dir: str, output_dir: str, filename_template: str = "{artist} - {title}"):
        self.download_dir = download_dir
        self.output_dir = output_dir
        self.filename_template = filename_template

        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"File processor initialized: downloads={download_dir}, output={output_dir}")

    def find_similar(self, query: str, threshold: float = 0.6) -> list[str]:
        """Find files in the library with names similar to the query."""
        if not os.path.isdir(self.output_dir):
            return []

        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))

        matches = []
        for filename in os.listdir(self.output_dir):
            _, ext = os.path.splitext(filename)
            if ext.lower() not in _AUDIO_EXTENSIONS:
                continue

            stem = os.path.splitext(filename)[0].lower()
            stem_words = set(re.findall(r"\w+", stem))

            if query_words and stem_words:
                common = query_words & stem_words
                word_ratio = len(common) / min(len(query_words), len(stem_words))
            else:
                word_ratio = 0.0

            seq_ratio = SequenceMatcher(None, query_lower, stem).ratio()
            best_ratio = max(word_ratio, seq_ratio)

            if best_ratio >= threshold:
                matches.append((filename, best_ratio))

        matches.sort(key=lambda x: x[1], reverse=True)
        return [m[0] for m in matches]

    def find_exact(self, artist: str, title: str) -> list[str]:
        """Return library files whose stem matches the configured filename template."""
        if not os.path.isdir(self.output_dir):
            return []
        stem = self._sanitize_filename(self.filename_template.format(artist=artist, title=title)).lower()
        matches = []
        for filename in os.listdir(self.output_dir):
            name, ext = os.path.splitext(filename)
            if ext.lower() not in _AUDIO_EXTENSIONS:
                continue
            if name.lower() == stem:
                matches.append(filename)
        return matches

    def build_filename(self, artist: str, title: str, extension: str = "flac") -> str:
        """Build the target filename from artist and title."""
        name = self.filename_template.format(artist=artist, title=title)
        name = self._sanitize_filename(name)
        return f"{name}.{extension}"

    def find_downloaded_file(self, username: str, remote_filename: str) -> str | None:
        """Find a downloaded file on disk based on the slskd download structure."""
        basename = remote_filename.replace("\\", "/").rsplit("/", 1)[-1]

        user_dir = os.path.join(self.download_dir, username)

        real_user_dir = os.path.realpath(user_dir)
        real_download_dir = os.path.realpath(self.download_dir)
        if not real_user_dir.startswith(real_download_dir + os.sep) and real_user_dir != real_download_dir:
            logger.warning("Path traversal blocked for username: %s", username)
            return None

        if os.path.isdir(user_dir):
            for root, _, files in os.walk(user_dir):
                if basename in files:
                    path = os.path.join(root, basename)
                    logger.info(f"Found downloaded file: {path}")
                    return path

        for root, _, files in os.walk(self.download_dir):
            if basename in files:
                path = os.path.join(root, basename)
                logger.info(f"Found downloaded file (fallback): {path}")
                return path

        logger.warning(f"Downloaded file not found: {basename} (user={username})")
        return None

    def process_file(self, source_path: str, artist: str, title: str) -> str | None:
        """Rename and move a downloaded file to the library directory."""
        try:
            if not os.path.isfile(source_path):
                logger.error(f"Source file does not exist: {source_path}")
                return None

            _, ext = os.path.splitext(source_path)
            extension = ext.lstrip(".").lower() or "flac"

            target_name = self.build_filename(artist, title, extension)
            target_path = os.path.join(self.output_dir, target_name)

            if os.path.exists(target_path):
                logger.warning(f"File already exists: {target_path}")
                base, ext_with_dot = os.path.splitext(target_path)
                counter = 1
                while os.path.exists(target_path):
                    target_path = f"{base} ({counter}){ext_with_dot}"
                    counter += 1

            tmp_path = target_path + ".importing"
            try:
                shutil.copy2(source_path, tmp_path)
                self._dedup_flac_tags(tmp_path)
                os.replace(tmp_path, target_path)
            except BaseException:
                with contextlib.suppress(OSError):
                    os.remove(tmp_path)
                raise
            logger.info(f"File placed: {target_path}")

            return target_path

        except Exception:
            logger.exception(f"Failed to process file: {source_path}")
            return None

    def cleanup_download(self, source_path: str) -> bool:
        """Remove the original downloaded file after successful processing."""
        try:
            if os.path.isfile(source_path):
                os.remove(source_path)
                logger.info(f"Cleaned up: {source_path}")

                parent = os.path.dirname(source_path)
                if os.path.isdir(parent) and not os.listdir(parent):
                    os.rmdir(parent)
                    logger.debug(f"Removed empty directory: {parent}")

                return True
            return False

        except Exception:
            logger.exception(f"Failed to cleanup: {source_path}")
            return False

    @staticmethod
    def _dedup_flac_tags(filepath: str) -> None:
        """Remove exact duplicate Vorbis comment values in a FLAC file."""
        try:
            audio = mutagen.flac.FLAC(filepath)
            changed = False
            for key in list(audio.keys()):
                values = audio.get(key, [])
                if len(values) <= 1:
                    continue
                seen: list[str] = []
                for v in values:
                    if v not in seen:
                        seen.append(v)
                if len(seen) < len(values):
                    audio[key] = seen
                    changed = True
            if changed:
                audio.save()
                logger.info("Deduplicated FLAC tags: %s", os.path.basename(filepath))
        except Exception:
            logger.debug("Tag dedup failed for %s", filepath, exc_info=True)

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        """Remove or replace characters that are invalid in filenames."""
        name = re.sub(r'[<>:"/\\|?*]', "", name)
        name = re.sub(r"\s+", " ", name)
        name = name.strip(" .")
        return name
