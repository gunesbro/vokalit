"""Stub huggingface_hub: records downloads."""


def snapshot_download(repo_id, revision=None, **kwargs):
    print(f"stub download {repo_id}@{revision}")
    return f"/cache/{repo_id}"
