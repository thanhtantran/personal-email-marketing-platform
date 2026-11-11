"""Domain layer.

Business rules that are independent of HTTP and of the persistence mechanism.
Keeping them here makes the invariants in SPEC.md unit-testable without a
database.
"""
