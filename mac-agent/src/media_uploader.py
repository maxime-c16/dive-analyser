"""Upload finalized rendition artifacts to Debian."""

from .sync_client import SyncClient
from .transcoder import RenditionArtifact


class MediaUploader:
    """Thin wrapper around SyncClient media upload/finalize calls."""

    def __init__(self, sync_client: SyncClient, agent_id: str):
        self.sync_client = sync_client
        self.agent_id = agent_id

    async def upload_and_finalize(self, job_id: int, artifact: RenditionArtifact) -> dict:
        """Upload artifact then finalize cache entry."""
        await self.sync_client.upload_media_artifact(job_id, artifact, self.agent_id)
        result = await self.sync_client.finalize_media_job(job_id, artifact, self.agent_id)
        artifact.cleanup()
        return result
