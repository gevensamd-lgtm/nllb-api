"""Preserve and verify the exact public models inventoried in production."""

from hashlib import sha256
from pathlib import Path
from typing import Final

from huggingface_hub import hf_hub_download, snapshot_download

MODEL_PINS: Final[dict[str, tuple[str, dict[str, str]]]] = {
    "winstxnhdw/nllb-200-distilled-1.3B-ct2-int8": (
        "5d67ab73ef26497a7964712d7df01dfa1569dd04",
        {
            ".gitattributes": "73adcd4dae60ea6f867e3ea47d46231e38eb3cf9cabb2b492b6cfdaf1307b243",
            "README.md": "85e05ca1d158e304c175acedc01706fc015e1d495d7ce0d66a86276aa5f04b87",
            "config.json": "8f6496adfc930cbfecbe8281112197705c488fab47d34b4829b06d7f478909af",
            "model.bin": "d02c1ceb6d79dcd3ac06583d4f84060a49d248939ad6f7b00d60853b09c18702",
            "shared_vocabulary.json": "af53bfd0e6f726209e7325e45b87ab3b14e5856f7d42d7b9be91de3287c45267",
            "tokenizer.json": "e316b82de11d0f951f370943b3c438311629547285129b0b81dadabd01bca665",
        },
    ),
    "facebook/fasttext-language-identification": (
        "3af127d4124fc58b75666f3594bb5143b9757e78",
        {
            "model.bin": "8ded5749a2ad79ae9ab7c9190c7c8b97ff20d54ad8b9527ffa50107238fc7f6a",
        },
    ),
}
_CHUNK_BYTES: Final = 4 * 1024 * 1024


def pinned_revision(repository: str) -> str | None:
    """Return the deployed revision for known public models."""
    pin = MODEL_PINS.get(repository)
    return pin[0] if pin is not None else None


def verify_file(repository: str, filename: str, path: str) -> str:
    """Reject altered artifacts while retaining configured custom models."""
    pin = MODEL_PINS.get(repository)
    if pin is None:
        return path
    expected = pin[1].get(filename)
    if expected is None:
        message = f"Unpinned artifact requested from {repository}: {filename}"
        raise RuntimeError(message)
    digest = sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(_CHUNK_BYTES), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected:
        message = f"Model integrity mismatch: {repository}/{filename}"
        raise RuntimeError(message)
    return path


def verify_snapshot(repository: str, path: str) -> str:
    """Verify every pinned file needed by a known snapshot."""
    pin = MODEL_PINS.get(repository)
    if pin is not None:
        for filename in pin[1]:
            verify_file(repository, filename, str(Path(path) / filename))
    return path


def download_pinned_models() -> None:
    """Download the production artifacts by commit and check their hashes."""
    repository = "winstxnhdw/nllb-200-distilled-1.3B-ct2-int8"
    path = snapshot_download(
        repository,
        revision=pinned_revision(repository),
        allow_patterns=list(MODEL_PINS[repository][1]),
    )
    verify_snapshot(repository, path)
    repository = "facebook/fasttext-language-identification"
    path = hf_hub_download(repository, "model.bin", revision=pinned_revision(repository))
    verify_file(repository, "model.bin", path)


if __name__ == "__main__":
    download_pinned_models()
