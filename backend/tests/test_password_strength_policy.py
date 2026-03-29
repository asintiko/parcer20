import pytest

pytest.importorskip("jose")

from services.user_service import UserServiceError, validate_password_strength


@pytest.mark.parametrize(
    "password",
    [
        "",
        "short1!",
        "lowercase123!",
        "UPPERCASE123!",
        "NoDigits!!",
        "NoSymbols123",
    ],
)
def test_validate_password_strength_rejects_weak(password: str) -> None:
    with pytest.raises(UserServiceError):
        validate_password_strength(password)


def test_validate_password_strength_accepts_strong() -> None:
    validate_password_strength("Str0ng!Pass123")
