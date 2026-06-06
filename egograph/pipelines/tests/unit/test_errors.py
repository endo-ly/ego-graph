"""Pipelines domain errors のテスト。"""

from pipelines.domain.errors import AuthenticationError, PipelinesError


def test_authentication_error_inherits_pipelines_error():
    """AuthenticationError は PipelinesError を継承する。"""
    # Arrange & Act
    err = AuthenticationError("token revoked")

    # Assert
    assert isinstance(err, PipelinesError)
    assert str(err) == "token revoked"


def test_authentication_error_preserves_cause_chain():
    """`raise X from e` で受け取った元の例外を __cause__ に保持する。"""
    # Arrange
    original = ValueError("spotipy raised this")

    # Act
    try:
        raise AuthenticationError("wrapped") from original
    except AuthenticationError as err:
        # Assert
        assert err.__cause__ is original
