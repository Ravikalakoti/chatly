from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .utils import normalize_email


class IdentifierBackend(ModelBackend):
    """Authenticate with an email address plus password. (Class name kept so settings don't change.)"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        email = normalize_email(username)
        if not email or not password:
            return None
        User = get_user_model()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Run the hasher anyway so response time doesn't reveal whether the account exists.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
