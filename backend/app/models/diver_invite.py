"""Diver invitation links: admin-minted signup tokens for unclaimed divers.

Maps exactly the table created by backend/migrations/add_diver_invites.sql.
See that file for the product and security contract.

One invite = one diver. Redeeming does NOT log anyone in as an existing
account: it creates a fresh friend-role AppUser and binds it OWNER of the
invited diver, so the clips already tied to that diver name become theirs.
"""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, text

from app.database import Base


class DiverInvite(Base):
    """Single-purpose signup token for one diver identity.

    Only the SHA-256 hash is stored (same pattern as user_sessions and
    claim_tokens). The raw token is returned exactly once, at mint time.
    """

    __tablename__ = "diver_invites"

    id = Column(Integer, primary_key=True, index=True)
    diver_id = Column(Integer, ForeignKey("divers.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(64), nullable=False, unique=True, index=True)
    created_by_user_id = Column(
        Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True
    )
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    # Filled at redeem time: the account the link created (NULL while live).
    user_id = Column(Integer, ForeignKey("app_users.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_diver_invites_live", "diver_id", "used_at", "revoked_at"),
        # One LIVE invite per diver, enforced by the database rather than by
        # application timing: concurrent mints serialize here and exactly one
        # wins, so a bearer credential never accumulates. Partial (WHERE) and
        # therefore not portable to every dialect — Postgres and SQLite, the
        # two we support, both honour it.
        Index(
            "uq_diver_invites_one_live",
            "diver_id",
            unique=True,
            sqlite_where=text("used_at IS NULL AND revoked_at IS NULL"),
            postgresql_where=text("used_at IS NULL AND revoked_at IS NULL"),
        ),
    )

    @property
    def is_live(self) -> bool:
        """Still redeemable: unused, unrevoked and unexpired."""
        return (
            self.used_at is None
            and self.revoked_at is None
            and self.expires_at > datetime.utcnow()
        )
