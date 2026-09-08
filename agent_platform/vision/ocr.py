"""OCR abstraction — callers are never bound to a single engine.

Providers:
  * :class:`TesseractOCR`  — pytesseract (cross-platform, needs tesseract binary)
  * :class:`WindowsOCR`    — Windows.Media.Ocr via winrt (Windows native)
  * :class:`PlaceholderOCR` — honest fallback that reports a LIMITATION instead
    of pretending.

Registry picks the best available provider at runtime; the system never ties
itself to one engine.
"""

from __future__ import annotations

import abc
from typing import Any, Optional


class OCRProvider(abc.ABC):
    name = "base"

    @abc.abstractmethod
    def available(self) -> bool:
        """True if this provider can actually run on this machine."""

    @abc.abstractmethod
    def read_text(self, image_path: str) -> str:
        """Return the text found in an image file."""

    def last_error(self) -> str:
        return ""


class TesseractOCR(OCRProvider):
    name = "tesseract"

    def available(self) -> bool:
        try:
            import pytesseract  # noqa: F401
            import shutil

            return shutil.which("tesseract") is not None
        except Exception:  # noqa: BLE001
            return False

    def read_text(self, image_path: str) -> str:
        import pytesseract

        return pytesseract.image_to_string(image_path)


class WindowsOCR(OCRProvider):
    """Windows.Media.Ocr via the winrt package (native, no external binary)."""

    name = "windows"

    def __init__(self) -> None:
        self._engine = None
        self._err = ""

    def available(self) -> bool:
        try:
            import winrt.windows.media.ocr as ocr  # noqa: F401
            import winrt.windows.graphics.imaging as gi  # noqa: F401

            return True
        except Exception as exc:  # noqa: BLE001
            self._err = str(exc)
            return False

    def read_text(self, image_path: str) -> str:
        import asyncio

        return asyncio.run(self._read_async(image_path))

    async def _read_async(self, image_path: str) -> str:
        import winrt.windows.media.ocr as ocr
        import winrt.windows.graphics.imaging as gi
        import winrt.windows.storage.streams as streams

        engine = ocr.OcrEngine.try_create_from_user_profile_languages()
        file = await gi.BitmapDecoder.create_async(
            await streams.RandomAccessStreamReference.create_from_file(
                await _storage_file(image_path)).open_read_async())
        bitmap = await file.get_software_bitmap_async()
        result = await engine.recognize_async(bitmap)
        return result.text


async def _storage_file(path: str):
    import winrt.windows.storage as storage

    return await storage.StorageFile.get_file_from_path_async(path)


class PlaceholderOCR(OCRProvider):
    """Honest fallback: reports the capability is unavailable, never fakes it."""
    name = "unavailable"

    def available(self) -> bool:
        return False

    def read_text(self, image_path: str) -> str:
        raise RuntimeError("LIMITATION: no OCR engine available. Install Tesseract "
                           "or run on Windows (WindowsOCR).")


class OCRRegistry:
    def __init__(self) -> None:
        self._providers: list[OCRProvider] = [
            WindowsOCR(),
            TesseractOCR(),
            PlaceholderOCR(),
        ]

    def best(self) -> OCRProvider:
        for p in self._providers:
            if p.available():
                return p
        return self._providers[-1]

    def available_names(self) -> list[str]:
        return [p.name for p in self._providers if p.available()]

    def read_text(self, image_path: str) -> tuple[str, str]:
        """Return (text, provider_name). Raises if no engine available."""
        provider = self.best()
        if not provider.available():
            raise RuntimeError("LIMITATION: no OCR engine available. "
                               f"Tried: {', '.join(p.name for p in self._providers)}")
        return provider.read_text(image_path), provider.name


def get_ocr_registry() -> OCRRegistry:
    return OCRRegistry()
