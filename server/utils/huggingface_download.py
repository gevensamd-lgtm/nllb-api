from huggingface_hub import snapshot_download

from server.model_integrity import pinned_revision, verify_snapshot
from server.utils.has_internet_access import has_internet_access


def huggingface_download(repository: str) -> str:
    """
    Summary
    -------
    download the huggingface model

    Parameters
    ----------
    repository (str) : the name of the Hugging Face repository

    Returns
    -------
    repository_path (str) : local path to the downloaded repository
    """
    return verify_snapshot(
        repository,
        snapshot_download(
            repository,
            revision=pinned_revision(repository),
            local_files_only=not has_internet_access(repository),
        ),
    )
