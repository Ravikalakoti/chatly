from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .utils import parse_identifier


class IdentifierBackend(ModelBackend):
    """Authenticate with an email address or a phone number plus password."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        kind, value = parse_identifier(username)
        if not kind:
            return None
        User = get_user_model()
        try:
            user = User.objects.get(**{kind: value})
        except User.DoesNotExist:
            # Run the hasher anyway so response time doesn't reveal whether the account exists.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
