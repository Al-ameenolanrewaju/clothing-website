import os
from uuid import uuid4

import cloudinary
import cloudinary.uploader
from cloudinary.exceptions import Error as CloudinaryError
from werkzeug.datastructures import FileStorage


class MediaError(RuntimeError):
    pass


ALLOWED_IMAGE_TYPES = {
    "jpeg": lambda data: data.startswith(b"\xff\xd8\xff"),
    "png": lambda data: data.startswith(b"\x89PNG\r\n\x1a\n"),
    "webp": lambda data: len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP",
}


def validate_image(file: FileStorage):
    if not file or not file.filename:
        raise ValueError("Choose an image file.")
    header = file.stream.read(12)
    file.stream.seek(0)
    if not any(signature(header) for signature in ALLOWED_IMAGE_TYPES.values()):
        raise ValueError("Use a valid JPEG, PNG or WebP image.")


def _configure_cloudinary():
    cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
    api_key = os.getenv("CLOUDINARY_API_KEY")
    api_secret = os.getenv("CLOUDINARY_API_SECRET")
    if not all((cloud_name, api_key, api_secret)):
        raise RuntimeError("Image uploads require Cloudinary credentials to be configured.")
    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )


def upload_image(file: FileStorage, folder: str):
    validate_image(file)
    _configure_cloudinary()
    try:
        result = cloudinary.uploader.upload(
            file,
            folder=folder,
            public_id=uuid4().hex,
            resource_type="image",
            overwrite=False,
            unique_filename=False,
            use_filename=False,
        )
    except CloudinaryError as error:
        raise MediaError("Cloudinary could not upload the image.") from error
    public_id = result["public_id"]
    url = cloudinary.CloudinaryImage(public_id).build_url(
        secure=True,
        quality="auto",
        fetch_format="auto",
        width=1600,
        crop="limit",
    )
    return url, public_id


def delete_image(public_id: str):
    _configure_cloudinary()
    try:
        result = cloudinary.uploader.destroy(public_id, resource_type="image", invalidate=True)
    except CloudinaryError as error:
        raise MediaError("Cloudinary could not delete the image.") from error
    if result.get("result") not in {"ok", "not found"}:
        raise RuntimeError("Cloudinary did not confirm image deletion.")
