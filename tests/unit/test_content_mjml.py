"""The MJML renderer contract is testable without a Node.js toolchain."""

from __future__ import annotations

import pytest

from app.domain.content.mjml import MjmlRenderError, render_mjml

SOURCE = "<mjml><mj-body></mj-body></mjml>"


def test_empty_source_is_rejected() -> None:
    with pytest.raises(MjmlRenderError):
        render_mjml("   ")


def test_injected_runner_result_is_returned() -> None:
    def runner(source: str, *, binary: str, timeout: int) -> str:
        assert source == SOURCE
        assert binary == "mjml"
        assert timeout == 20
        return "<html><body>rendered</body></html>"

    assert render_mjml(SOURCE, runner=runner) == "<html><body>rendered</body></html>"


def test_missing_binary_fails_closed() -> None:
    with pytest.raises(MjmlRenderError) as excinfo:
        render_mjml(SOURCE, binary="definitely-not-a-real-mjml-binary-xyz")
    assert excinfo.value.extra.get("reason") == "mjml_unavailable"


def test_runner_errors_propagate() -> None:
    def runner(source: str, *, binary: str, timeout: int) -> str:
        raise MjmlRenderError("boom", extra={"reason": "mjml_failed"})

    with pytest.raises(MjmlRenderError):
        render_mjml(SOURCE, runner=runner)
