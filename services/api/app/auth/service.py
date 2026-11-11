"""Authentication service: owner allowlist, session issuance and revocation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.oidc import GoogleIdentity
from app.config import Settings
from app.db.models import AuthSession, Membership, Tenant, User
from app.errors import ForbiddenError
from app.logging import get_logger
from app.repositories.audit_repo import AuditRepository
from app.repositories.membership_repo import MembershipRepository
from app.repositories.session_repo import SessionRepository
from app.repositories.tenant_repo import TenantRepository
from app.repositories.user_repo import UserRepository
from app.security.tokens import generate_token, hash_token

logger = get_logger(__name__)


@dataclass(frozen=True)
class IssuedSession:
    session: AuthSession
    token: str
    tenant: Tenant
    user: User
    expires_at: datetime


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _owner_matches(self, identity: GoogleIdentity) -> bool:
        if self.settings.owner_google_sub:
            return identity.subject == self.settings.owner_google_sub
        if self.settings.owner_email:
            return (
                identity.email_verified
                and identity.email.lower() == self.settings.owner_email.lower()
            )
        return False

    def _authorize_owner(self, identity: GoogleIdentity) -> None:
        """Enforce the single-owner allowlist. Fails closed for everyone else."""
        if self.settings.owner_configured:
            if not self._owner_matches(identity):
                logger.warning(
                    "non-owner identity rejected",
                    extra={"google_subject": identity.subject},
                )
                raise ForbiddenError("This identity is not the configured workspace owner")
            return

        # No owner configured: only a development/test deployment may claim the
        # first identity as owner. Production fails closed.
        if self.settings.app_env.lower() in {"development", "test"}:
            logger.warning(
                "OWNER_GOOGLE_SUB/OWNER_EMAIL not configured; claiming first identity as owner "
                "because APP_ENV is not production. Configure the owner before any real deployment."
            )
            return

        raise ForbiddenError("Workspace owner is not configured; refusing login")

    async def complete_login(self, identity: GoogleIdentity) -> IssuedSession:
        self._authorize_owner(identity)

        tenants = TenantRepository(self.session)
        users = UserRepository(self.session)
        memberships = MembershipRepository(self.session)
        sessions = SessionRepository(self.session)

        tenant = await tenants.get_by_slug(self.settings.tenant_slug)
        if tenant is None:
            tenant = await tenants.create(
                slug=self.settings.tenant_slug, name=self.settings.tenant_name
            )

        user = await users.get_by_subject(identity.subject)
        if user is None:
            user = await users.create(
                google_subject=identity.subject,
                email=identity.email,
                display_name=identity.name,
            )
        else:
            user.email = identity.email
            user.display_name = identity.name or user.display_name

        await users.update_last_login(user)
        membership: Membership = await memberships.ensure(
            tenant_id=tenant.id, user_id=user.id, role="owner", status="active"
        )

        token = generate_token()
        expires_at = datetime.now(UTC) + timedelta(hours=self.settings.session_absolute_hours)
        record = await sessions.create(
            tenant_id=tenant.id,
            user_id=user.id,
            token_hash=hash_token(token),
            expires_at=expires_at,
        )

        audit = AuditRepository(self.session, tenant.id)
        await audit.record(
            action="auth.login",
            actor_user_id=user.id,
            object_type="session",
            object_id=str(record.id),
            details={"role": membership.role},
        )

        await self.session.commit()
        logger.info("owner logged in", extra={"user_id": str(user.id), "tenant_id": str(tenant.id)})
        return IssuedSession(
            session=record, token=token, tenant=tenant, user=user, expires_at=expires_at
        )
