from django.test import TestCase
from django.urls import reverse

from chat.models import Conversation

from .models import User
from .utils import normalize_phone, parse_identifier


class UtilsTests(TestCase):
    def test_phone_normalisation(self):
        for raw in ("98765 43210", "09876543210", "+91 98765-43210", "0091 9876543210", "919876543210"):
            self.assertEqual(normalize_phone(raw), "+919876543210", raw)
        self.assertEqual(normalize_phone("+1 (415) 555-0132"), "+14155550132")
        self.assertIsNone(normalize_phone("12ab"))
        self.assertIsNone(normalize_phone(""))

    def test_identifier_parsing(self):
        self.assertEqual(parse_identifier(" Me@Example.COM "), ("email", "me@example.com"))
        self.assertEqual(parse_identifier("98765 43210"), ("phone", "+919876543210"))
        self.assertEqual(parse_identifier("not-an-email@"), (None, None))


def make_user(name, email=None, phone=None, password="s3cret-pass!"):
    user = User(display_name=name, email=email, phone=phone)
    user.set_password(password)
    user.save()
    return user


class AuthFlowTests(TestCase):
    def signup(self, identifier, name="Asha", password="s3cret-pass!", url=None):
        return self.client.post(
            url or reverse("signup"),
            {"display_name": name, "identifier": identifier, "password1": password, "password2": password},
        )

    def test_signup_with_email_then_login(self):
        resp = self.signup("asha@example.com")
        self.assertRedirects(resp, reverse("home"))
        self.client.post(reverse("logout"))
        resp = self.client.post(reverse("login"), {"identifier": "ASHA@example.com", "password": "s3cret-pass!"})
        self.assertRedirects(resp, reverse("home"))

    def test_signup_with_phone_then_login_with_different_formatting(self):
        self.signup("98765 43210")
        self.client.post(reverse("logout"))
        resp = self.client.post(reverse("login"), {"identifier": "+91 9876543210", "password": "s3cret-pass!"})
        self.assertRedirects(resp, reverse("home"))

    def test_duplicate_and_bad_input(self):
        self.signup("asha@example.com")
        self.client.post(reverse("logout"))
        resp = self.signup("asha@example.com", name="Other")
        self.assertContains(resp, "already exists")
        resp = self.signup("garbage")
        self.assertContains(resp, "valid phone number or email")
        resp = self.client.post(
            reverse("signup"),
            {"display_name": "X", "identifier": "x@example.com", "password1": "abcdefgh1", "password2": "different1"},
        )
        self.assertContains(resp, "don&#x27;t match")

    def test_wrong_password(self):
        make_user("Asha", email="asha@example.com")
        resp = self.client.post(reverse("login"), {"identifier": "asha@example.com", "password": "nope"})
        self.assertContains(resp, "Incorrect phone/email or password")

    def test_home_requires_login(self):
        resp = self.client.get(reverse("home"))
        self.assertRedirects(resp, f"{reverse('login')}?next=/", fetch_redirect_response=False)


class InviteFlowTests(TestCase):
    def setUp(self):
        self.inviter = make_user("Ravi", email="ravi@example.com")

    def test_home_shows_invite_link(self):
        self.client.force_login(self.inviter)
        resp = self.client.get(reverse("home"))
        self.assertContains(resp, f"/invite/{self.inviter.invite_code}/")

    def test_new_user_signs_up_through_invite(self):
        url = reverse("invite", args=[self.inviter.invite_code])
        page = self.client.get(url)
        self.assertContains(page, "Ravi")
        self.assertContains(page, "invited you")

        resp = self.client.post(
            url,
            {"display_name": "Asha", "identifier": "9876543210", "password1": "s3cret-pass!", "password2": "s3cret-pass!"},
        )
        newcomer = User.objects.get(phone="+919876543210")
        conv = Conversation.objects.get()
        self.assertRedirects(resp, reverse("chat", args=[conv.pk]))
        self.assertEqual({conv.user_a, conv.user_b}, {self.inviter, newcomer})

    def test_existing_user_logs_in_through_invite(self):
        make_user("Asha", email="asha@example.com")
        self.client.get(reverse("invite", args=[self.inviter.invite_code]))  # remembers inviter in session
        resp = self.client.post(reverse("login"), {"identifier": "asha@example.com", "password": "s3cret-pass!"})
        conv = Conversation.objects.get()
        self.assertRedirects(resp, reverse("chat", args=[conv.pk]))

    def test_logged_in_user_opening_invite_gets_connected(self):
        other = make_user("Asha", email="asha@example.com")
        self.client.force_login(other)
        resp = self.client.get(reverse("invite", args=[self.inviter.invite_code]))
        conv = Conversation.objects.get()
        self.assertRedirects(resp, reverse("chat", args=[conv.pk]))
        # opening it again doesn't create a duplicate
        self.client.get(reverse("invite", args=[self.inviter.invite_code]))
        self.assertEqual(Conversation.objects.count(), 1)

    def test_own_link_and_bad_link(self):
        self.client.force_login(self.inviter)
        resp = self.client.get(reverse("invite", args=[self.inviter.invite_code]))
        self.assertRedirects(resp, reverse("home"))
        self.assertEqual(Conversation.objects.count(), 0)
        self.client.logout()
        resp = self.client.get(reverse("invite", args=["doesnotexist"]))
        self.assertRedirects(resp, reverse("signup"))
