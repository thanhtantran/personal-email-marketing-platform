from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Contact, ContactTag, Tag
from app.domain.audience.consent import eligible_contact_filter
from app.domain.audience.segments import build_filter
from app.repositories.base import TenantScopedRepository


def _like_pattern(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class ContactRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, contact_id: uuid.UUID) -> Contact | None:
        result = await self.session.execute(
            select(Contact).where(
                Contact.tenant_id == self.tenant_id,
                Contact.id == contact_id,
                Contact.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_by_email(self, normalized_email: str) -> Contact | None:
        result = await self.session.execute(
            select(Contact).where(
                Contact.tenant_id == self.tenant_id,
                Contact.normalized_email == normalized_email,
                Contact.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def existing_emails(self, emails: Iterable[str]) -> set[str]:
        values = list(emails)
        if not values:
            return set()
        result = await self.session.execute(
            select(Contact.normalized_email).where(
                Contact.tenant_id == self.tenant_id,
                Contact.normalized_email.in_(values),
            )
        )
        return set(result.scalars().all())

    async def list_by_emails(self, emails: Iterable[str]) -> dict[str, Contact]:
        values = list(emails)
        if not values:
            return {}
        result = await self.session.execute(
            select(Contact).where(
                Contact.tenant_id == self.tenant_id,
                Contact.normalized_email.in_(values),
            )
        )
        return {contact.normalized_email: contact for contact in result.scalars().all()}

    async def create(
        self,
        *,
        normalized_email: str,
        email_display: str,
        status: str = "active",
        consent_status: str = "unknown",
        consent_at: datetime | None = None,
        consent_source: str | None = None,
        consent_evidence_ref: str | None = None,
        attributes: dict | None = None,
    ) -> Contact:
        contact = Contact(
            tenant_id=self.tenant_id,
            normalized_email=normalized_email,
            email_display=email_display,
            status=status,
            consent_status=consent_status,
            consent_at=consent_at,
            consent_source=consent_source,
            consent_evidence_ref=consent_evidence_ref,
            attributes=attributes or {},
        )
        self.session.add(contact)
        await self.session.flush()
        return contact

    async def apply_fields(self, contact: Contact, fields: dict) -> Contact:
        for key, value in fields.items():
            setattr(contact, key, value)
        await self.session.flush()
        return contact

    async def soft_delete(self, contact: Contact, when: datetime | None = None) -> None:
        contact.deleted_at = when or datetime.now(UTC)
        await self.session.flush()

    async def list_page(
        self,
        *,
        limit: int,
        cursor: tuple[datetime, uuid.UUID] | None = None,
        status: str | None = None,
        consent_status: str | None = None,
        tag_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> list[Contact]:
        stmt = select(Contact).where(
            Contact.tenant_id == self.tenant_id, Contact.deleted_at.is_(None)
        )
        if status:
            stmt = stmt.where(Contact.status == status)
        if consent_status:
            stmt = stmt.where(Contact.consent_status == consent_status)
        if tag_id:
            stmt = stmt.where(
                select(ContactTag.contact_id)
                .where(
                    ContactTag.tenant_id == self.tenant_id,
                    ContactTag.contact_id == Contact.id,
                    ContactTag.tag_id == tag_id,
                )
                .exists()
            )
        if search:
            pattern = _like_pattern(search.strip())
            stmt = stmt.where(
                or_(
                    Contact.normalized_email.ilike(pattern, escape="\\"),
                    Contact.email_display.ilike(pattern, escape="\\"),
                )
            )
        if cursor:
            stmt = stmt.where(tuple_(Contact.created_at, Contact.id) < tuple_(*cursor))
        stmt = stmt.order_by(Contact.created_at.desc(), Contact.id.desc()).limit(limit + 1)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(Contact)
            .where(Contact.tenant_id == self.tenant_id, Contact.deleted_at.is_(None))
        )
        return int(result.scalar_one())

    async def list_eligible(
        self,
        definition: dict,
        *,
        limit: int,
        after: tuple[str, uuid.UUID] | None = None,
    ) -> list[Contact]:
        """Page over contacts that are eligible to receive a marketing send.

        Ordered by ``(normalized_email, id)`` so a cursor of
        ``(normalized_email, id)`` walks the set in stable bounded batches
        without skipping or repeating rows as the ledger is built.
        """
        stmt = select(Contact).where(
            eligible_contact_filter(self.tenant_id),
            build_filter(definition, self.tenant_id),
        )
        if after:
            stmt = stmt.where(
                tuple_(Contact.normalized_email, Contact.id) > tuple_(*after)
            )
        stmt = stmt.order_by(Contact.normalized_email, Contact.id).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class TagRepository(TenantScopedRepository):
    def __init__(self, session: AsyncSession, tenant_id: uuid.UUID) -> None:
        super().__init__(session, tenant_id)

    async def get(self, tag_id: uuid.UUID) -> Tag | None:
        result = await self.session.execute(
            select(Tag).where(Tag.tenant_id == self.tenant_id, Tag.id == tag_id)
        )
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Tag]:
        result = await self.session.execute(
            select(Tag).where(Tag.tenant_id == self.tenant_id).order_by(Tag.name)
        )
        return list(result.scalars().all())

    async def get_or_create(self, name: str) -> Tag:
        normalized = name.strip().lower()
        result = await self.session.execute(
            select(Tag).where(Tag.tenant_id == self.tenant_id, Tag.normalized_name == normalized)
        )
        tag = result.scalar_one_or_none()
        if tag is not None:
            return tag
        tag = Tag(tenant_id=self.tenant_id, name=name.strip(), normalized_name=normalized)
        self.session.add(tag)
        await self.session.flush()
        return tag

    async def attach(self, contact_id: uuid.UUID, tag_id: uuid.UUID) -> None:
        existing = await self.session.execute(
            select(ContactTag).where(
                ContactTag.tenant_id == self.tenant_id,
                ContactTag.contact_id == contact_id,
                ContactTag.tag_id == tag_id,
            )
        )
        if existing.scalar_one_or_none() is not None:
            return
        self.session.add(
            ContactTag(tenant_id=self.tenant_id, contact_id=contact_id, tag_id=tag_id)
        )
        await self.session.flush()

    async def detach(self, contact_id: uuid.UUID, tag_id: uuid.UUID) -> None:
        result = await self.session.execute(
            select(ContactTag).where(
                ContactTag.tenant_id == self.tenant_id,
                ContactTag.contact_id == contact_id,
                ContactTag.tag_id == tag_id,
            )
        )
        record = result.scalar_one_or_none()
        if record is not None:
            await self.session.delete(record)
            await self.session.flush()

    async def tags_for_contact(self, contact_id: uuid.UUID) -> list[Tag]:
        result = await self.session.execute(
            select(Tag)
            .join(
                ContactTag,
                (ContactTag.tag_id == Tag.id) & (ContactTag.tenant_id == Tag.tenant_id),
            )
            .where(ContactTag.tenant_id == self.tenant_id, ContactTag.contact_id == contact_id)
            .order_by(Tag.name)
        )
        return list(result.scalars().all())
