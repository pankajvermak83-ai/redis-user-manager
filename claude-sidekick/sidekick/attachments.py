"""Pictures and files that can be sent along with a question."""

from __future__ import annotations

import base64
import io
import os
import tempfile
from dataclasses import dataclass

# Formats Claude accepts as pictures.
IMAGE_TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".webp": "image/webp",
}
# Pictures Sidekick converts to PNG first (needs the Pillow library).
CONVERTIBLE_IMAGES = {".bmp", ".tif", ".tiff"}
OFFICE_FILES = {".doc", ".docx", ".xls", ".xlsx", ".xlsm", ".ppt", ".pptx", ".odt", ".ods", ".odp"}

MAX_IMAGE_BYTES = 3_500_000
MAX_PDF_BYTES = 20_000_000
MAX_TEXT_FILE_BYTES = 400_000


class AttachmentError(Exception):
    """Why something could not be attached, in words meant for the user."""


@dataclass
class Attachment:
    kind: str  # "image", "pdf" or "text"
    name: str
    media_type: str
    data: bytes
    detail: str = ""  # e.g. "1280 x 720" or "240 KB"
    path: str = ""  # where the file is on disk ("" for a snipped picture)

    def describe(self) -> str:
        label = {"image": "Picture", "pdf": "PDF", "text": "File"}[self.kind]
        text = f"{label}: {self.name}" if self.name else label
        return f"{text} ({self.detail})" if self.detail else text

    def content_block(self) -> dict | None:
        """The piece of the API request that carries this picture or PDF.
        Text files return None: their words go inside the question instead."""
        encoded = base64.standard_b64encode(self.data).decode("ascii")
        if self.kind == "image":
            return {"type": "image", "source": {"type": "base64", "media_type": self.media_type, "data": encoded}}
        if self.kind == "pdf":
            return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": encoded}}
        return None

    def text(self) -> str:
        return _decode_text(self.data) if self.kind == "text" else ""


def _size_label(n: int) -> str:
    if n < 1_000_000:
        return f"{max(1, round(n / 1000))} KB"
    return f"{n / 1_000_000:.1f} MB"


def _pillow():
    try:
        from PIL import Image

        return Image
    except Exception:
        return None


def image_attachment(img: object, name: str, max_edge: int) -> Attachment:
    """Turn a picture (a Pillow image) into an attachment: shrink it so its
    longest side is at most `max_edge`, then save it as PNG (or JPEG when the
    PNG would be too big to send)."""
    Image = _pillow()
    if Image is None:
        raise AttachmentError("Pictures need the Pillow library. Run 1-Setup.bat again.")
    try:
        has_alpha = img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")
        img.thumbnail((max_edge, max_edge), Image.LANCZOS)  # only ever shrinks
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        data, media_type = buf.getvalue(), "image/png"
        if len(data) > MAX_IMAGE_BYTES:
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.split()[-1] if has_alpha else None)
            buf = io.BytesIO()
            flat.save(buf, format="JPEG", quality=85)
            data, media_type = buf.getvalue(), "image/jpeg"
    except AttachmentError:
        raise
    except Exception as e:
        raise AttachmentError(f"That picture could not be read ({type(e).__name__}).") from e
    if len(data) > MAX_IMAGE_BYTES:
        raise AttachmentError("That picture is too big to send. Snip a smaller area.")
    return Attachment("image", name, media_type, data, f"{img.width} x {img.height}")


def _decode_text(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8", errors="replace")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16", errors="replace")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def save_to_temp_file(attachment: Attachment) -> str:
    """Save a picture to Windows' temporary folder (so it can be dragged into
    another app) and return where it went. The same name is reused each time,
    so these files do not pile up."""
    folder = os.path.join(tempfile.gettempdir(), "Sidekick")
    os.makedirs(folder, exist_ok=True)
    ext = ".jpg" if attachment.media_type == "image/jpeg" else ".png"
    path = os.path.join(folder, "Sidekick picture" + ext)
    with open(path, "wb") as f:
        f.write(attachment.data)
    attachment.path = path
    attachment.name = attachment.name or os.path.basename(path)
    return path


def attachment_from_path(path: str, max_edge: int) -> Attachment:
    """Load a file from disk as an attachment, or raise AttachmentError
    explaining (in plain words) why it cannot be used."""
    attachment = _load_file(path, max_edge)
    attachment.path = path
    return attachment


def _load_file(path: str, max_edge: int) -> Attachment:
    name = os.path.basename(path)
    ext = os.path.splitext(name)[1].lower()
    try:
        size = os.path.getsize(path)
    except OSError as e:
        raise AttachmentError(f"'{name}' could not be opened.") from e
    if os.path.isdir(path):
        raise AttachmentError(f"'{name}' is a folder. Pick a single file.")
    if size == 0:
        raise AttachmentError(f"'{name}' is empty.")

    if ext in OFFICE_FILES:
        raise AttachmentError(
            "Sidekick cannot open Word, Excel or PowerPoint files directly.\n\n"
            "Open the file, select the part you need, press Ctrl+C, then press the "
            "Sidekick hotkey. Or save the file as a PDF and attach that."
        )

    if ext in IMAGE_TYPES or ext in CONVERTIBLE_IMAGES:
        Image = _pillow()
        if Image is not None:
            try:
                with Image.open(path) as img:
                    img.load()
                    return image_attachment(img, name, max_edge)
            except AttachmentError:
                raise
            except Exception as e:
                raise AttachmentError(f"'{name}' could not be read as a picture.") from e
        if ext in IMAGE_TYPES and size <= MAX_IMAGE_BYTES:
            with open(path, "rb") as f:
                return Attachment("image", name, IMAGE_TYPES[ext], f.read(), _size_label(size))
        raise AttachmentError("This picture needs the Pillow library. Run 1-Setup.bat again.")

    if ext == ".pdf":
        if size > MAX_PDF_BYTES:
            raise AttachmentError(
                f"'{name}' is {_size_label(size)}, which is too big to send. "
                "Copy the pages or text you need instead."
            )
        with open(path, "rb") as f:
            data = f.read()
        if not data.startswith(b"%PDF"):
            raise AttachmentError(f"'{name}' does not look like a real PDF file.")
        return Attachment("pdf", name, "application/pdf", data, _size_label(size))

    # Anything else is tried as plain text (notes, CSV, code, logs...).
    if size > MAX_TEXT_FILE_BYTES:
        raise AttachmentError(
            f"'{name}' is {_size_label(size)}, which is too big to send as text. "
            "Copy just the part you need (Ctrl+C) and press the hotkey."
        )
    with open(path, "rb") as f:
        data = f.read()
    is_utf16 = data.startswith((b"\xff\xfe", b"\xfe\xff"))
    if b"\x00" in data and not is_utf16:
        raise AttachmentError(
            f"Sidekick cannot read '{name}' (it is not a text, PDF or picture file).\n\n"
            "Open it in its own app, copy what you need, then press the hotkey."
        )
    return Attachment("text", name, "text/plain", data, _size_label(size))
