"""Database models"""

from app.models.session import Session
from app.models.dive import Dive
from app.models.dive_code import DiveCode
from app.models.cache import AnalyticsCache
from app.models.job import Job
from app.models.audit import AuditLog
from app.models.journey import Journey, JourneyMilestone
from app.models.fina_dive_code import FINADiveCode
from app.models.dd_lookup import DDLookup
from app.models.fina_scoring_rule import FINAScoringRule
from app.models.judge_score import JudgePanel, JudgeScore
from app.models.execution_fault import ExecutionFault
from app.models.migration_log import MigrationLog
from app.models.competition_event import (
    CompetitionEvent,
    CompetitionRound,
    CompetitionHeat,
    CompetitionCompetitor,
    CompetitionDiveEntry,
)
from app.models.emotional_state import EmotionalState, RecoveryPlan
from app.models.video_label import VideoLabel
from app.models.photos_asset import PhotosAsset, PhotosAssetAgentIdentity
from app.models.dive_modifier import DiveModifier
from app.models.media import (
    MediaCacheEntry,
    MediaJob,
    MediaPopulationRun,
    MediaPopulationRunItem,
    RepresentativeMediaSelection,
    MediaAgent,
    RecalledMediaSource,
)
from app.models.media_catalog import (
    CaptionedMediaCatalog,
    MediaCatalogRun,
    MediaCatalogPopulationRun,
    MediaCatalogPopulationItem,
    MediaResolutionUpgradeRun,
    MediaResolutionUpgradeItem,
)
from app.models.diver import Diver, DiverAlias
from app.models.training_period import TrainingPeriod
from app.models.media_backbone import (
    MediaBlob,
    MediaBlobLocation,
    MediaRevision,
    CaptionRevision,
    IngestObjectState,
)
from app.models.user_auth import (
    AppUser,
    UserCredential,
    UserSession,
    UserDiverAccess,
    LoginAttempt,
    MediaPlaybackGrant,
)

__all__ = [
    "Session",
    "Dive",
    "DiveCode",
    "AnalyticsCache",
    "Job",
    "AuditLog",
    "Journey",
    "JourneyMilestone",
    "FINADiveCode",
    "DDLookup",
    "FINAScoringRule",
    "JudgePanel",
    "JudgeScore",
    "ExecutionFault",
    "MigrationLog",
    "CompetitionEvent",
    "CompetitionRound",
    "CompetitionHeat",
    "CompetitionCompetitor",
    "CompetitionDiveEntry",
    "EmotionalState",
    "RecoveryPlan",
    "VideoLabel",
    "PhotosAsset",
    "PhotosAssetAgentIdentity",
    "DiveModifier",
    "MediaCacheEntry",
    "MediaJob",
    "MediaPopulationRun",
    "MediaPopulationRunItem",
    "CaptionedMediaCatalog",
    "MediaCatalogRun",
    "MediaCatalogPopulationRun",
    "MediaCatalogPopulationItem",
    "MediaResolutionUpgradeRun",
    "MediaResolutionUpgradeItem",
    "RepresentativeMediaSelection",
    "MediaAgent",
    "RecalledMediaSource",
    "Diver",
    "DiverAlias",
    "TrainingPeriod",
    "MediaBlob",
    "MediaBlobLocation",
    "MediaRevision",
    "CaptionRevision",
    "IngestObjectState",
    "AppUser",
    "UserCredential",
    "UserSession",
    "UserDiverAccess",
    "LoginAttempt",
    "MediaPlaybackGrant",
]
from app.models.analysis import (
    AnalysisRun,
    AnalysisJob,
    AnalysisLandmark,
    AnalysisPhase,
    AnalysisMetric,
    AnalysisArtifact,
    AnalysisComparison,
    AnalysisComparisonArtifact,
    AnalysisComparisonMetric,
)

from app.models.dive_social import DiveLike, DiveComment, DiveCommentLike, DiveGuestCommentLike
from app.models.notification import Notification, PushSubscription, NotificationPref
from app.models.dive_share import DiveShare, DiveGuest, DiveGuestLike, DiveGuestAccess
from app.models.fediverse import UserFediversePrefs, DiveFediverseOptin
from app.models.evaluation import EvaluationRequest
