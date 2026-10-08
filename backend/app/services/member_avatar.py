"""Small shared identity contract for profiles, comments and future DMs.

Never access the deferred photo bytes while serializing an identity.
"""


def avatar_identity(user):
    return {
        "avatar_url": (f"/api/v1/users/{user.id}/avatar?v={user.avatar_updated_at.isoformat()}"
                       if user.avatar_updated_at and user.is_active else None),
        "avatar_hud": user.avatar_hud or "reticle",
    }
