from django.conf import settings
from django.utils import timezone
import requests
from django.contrib import messages
from django.http import JsonResponse
from django.contrib.auth.hashers import make_password
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404, redirect, render

from billing.catalog import free_limits, packs
from billing.limits import quota_rows, reset_label
from chat.services import connect_users, conversations_for, incoming_requests, recommended_profiles

from . import otp
from .forms import LoginForm, SignupForm, ProfileForm, OtpForm
from .models import User
from django.contrib.auth.forms import PasswordResetForm
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods

import logging

logger = logging.getLogger(__name__)

INVITE_SESSION_KEY = "invite_code"
AUTH_BACKEND = "accounts.backends.IdentifierBackend"


def _inviter_from_code(code, exclude=None):
    if not code:
        return None
    qs = User.objects.filter(invite_code=code)
    if exclude is not None:
        qs = qs.exclude(pk=exclude.pk)
    return qs.first()


def _finish_auth(request, user, default="home"):
    """
    Called right after signup/login. If the person arrived through an invite
    link, connect them with the inviter and land them straight in that chat.
    """
    code = request.session.get(INVITE_SESSION_KEY)  # read before login() rotates the session
    login(request, user, backend=AUTH_BACKEND)
    request.session.pop(INVITE_SESSION_KEY, None)
    inviter = _inviter_from_code(code, exclude=user)
    if inviter:
        conversation, created = connect_users(user, inviter)
        if created:
            messages.success(request, f"You're now connected with {inviter.name}. Say hi!")
        return redirect("chat", conversation_id=conversation.pk)
    return None


def home(request):
    """
    `/` is two pages in one:
    - logged out -> the public landing page (what Chatly is, free limits, packs, sign up / log in)
    - logged in  -> your home: invite link, today's messages left, shortcuts
    """
    if not request.user.is_authenticated:
        return render(
            request,
            "accounts/landing.html",
            {"limits": free_limits(), "packs": packs(), "reset_label": reset_label()},
        )
    invite_url = request.build_absolute_uri(reverse("invite", args=[request.user.invite_code]))
    suggestions, suggestion_limit = recommended_profiles(request.user)
    return render(
        request,
        "accounts/home.html",
        {
            "invite_url": invite_url,
            "rows": quota_rows(request.user),
            "reset_label": reset_label(),
            "recommended": suggestions,
            "recommended_limit": suggestion_limit,
            "needs_gender": request.user.gender not in ("male", "female"),
            "chat_requests": incoming_requests(request.user),
            "show_dev_notice": not request.user.seen_dev_notice,
            "dev_contact_name": settings.DEV_CONTACT_NAME,
            "dev_contact_email": settings.DEV_CONTACT_EMAIL,
        },
    )


def signup(request, code=None):
    """
    Serves both /signup/ and /invite/<code>/.

    - Logged-out visitor on an invite link  -> sign-up page (remembers the inviter).
    - Logged-in visitor on an invite link   -> connected to the inviter, opens the chat.
    """
    inviter = None
    if code:
        inviter = _inviter_from_code(code)
        if inviter is None:
            messages.error(request, "That invite link isn't valid. Ask your friend to send it again.")
            return redirect("signup")
        if request.user.is_authenticated:
            if inviter.pk == request.user.pk:
                messages.info(request, "That's your own invite link. Copy it and send it to a friend!")
                return redirect("home")
            conversation, created = connect_users(request.user, inviter)
            if created:
                messages.success(request, f"You're now connected with {inviter.name}.")
            return redirect("chat", conversation_id=conversation.pk)
        request.session[INVITE_SESSION_KEY] = code
    elif request.user.is_authenticated:
        return redirect("home")
    else:
        inviter = _inviter_from_code(request.session.get(INVITE_SESSION_KEY))

    form = SignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # Don't create the account yet: it is created only after the emailed code is verified.
        data = {
            "display_name": form.cleaned_data["display_name"],
            "date_of_birth": form.cleaned_data["date_of_birth"].isoformat(),
            "gender": form.cleaned_data["gender"],
            "email": form.cleaned_data["email"],
            "password": make_password(form.cleaned_data["password1"]),
        }
        if otp.start(request, purpose="signup", email=data["email"], name=data["display_name"], signup=data):
            return redirect("verify_otp")
        form.add_error(None, "We couldn't send the verification email. Please try again in a moment.")
    return render(request, "accounts/signup.html", {"form": form, "inviter": inviter})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    inviter = _inviter_from_code(request.session.get(INVITE_SESSION_KEY))
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    form = LoginForm(request, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.user
        safe_next = next_url if url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}) else ""
        if otp.start(request, purpose="login", email=user.email, name=user.name, user_id=user.pk, next_url=safe_next):
            return redirect("verify_otp")
        form.add_error(None, "We couldn't send the login code. Please try again in a moment.")
    return render(request, "accounts/login.html", {"form": form, "inviter": inviter, "next": next_url})


def verify_otp(request):
    """Step 2 of signup/login: enter the 6-digit code that was emailed."""
    data = otp.pending(request)
    is_verify_email = bool(data) and data["purpose"] == "verify_email"
    if not data:
        return redirect("profile" if request.user.is_authenticated else "login")
    if request.user.is_authenticated and not is_verify_email:
        return redirect("home")
    if is_verify_email and (not request.user.is_authenticated or data["user_id"] != request.user.pk):
        otp.clear(request)
        return redirect("login")

    form = OtpForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ok, error = otp.check(request, form.cleaned_data["code"])
        if not ok:
            form.add_error("code", error)
            if otp.pending(request) is None:  # expired / locked out
                messages.error(request, error)
                if is_verify_email:
                    return redirect("profile")
                return redirect("signup" if data["purpose"] == "signup" else "login")
        else:
            if is_verify_email:
                otp.clear(request)
                _mark_email_verified(request.user, data["email"])
                messages.success(request, "Your email is verified ✅")
                return redirect("profile")
            if data["purpose"] == "signup":
                s = data["signup"]
                if User.objects.filter(email=s["email"]).exists():
                    otp.clear(request)
                    messages.error(request, "An account with this email already exists. Try logging in.")
                    return redirect("login")
                user = User(
                    display_name=s["display_name"],
                    date_of_birth=s["date_of_birth"],
                    gender=s["gender"],
                    email=s["email"],
                    password=s["password"],
                )
                user.save()
                _mark_email_verified(user, s["email"])
            else:
                user = User.objects.filter(pk=data["user_id"]).first()
                if user is None:
                    otp.clear(request)
                    return redirect("login")
                _mark_email_verified(user, data["email"])
            otp.clear(request)
            response = _finish_auth(request, user)
            if response:
                return response
            return redirect(data.get("next") or "home")
    return render(
        request,
        "accounts/verify_otp.html",
        {"form": form, "email": _mask_email(data["email"]), "purpose": data["purpose"]},
    )


@require_POST
def resend_otp(request):
    ok, message = otp.resend(request)
    (messages.success if ok else messages.error)(request, message)
    return redirect("verify_otp" if otp.pending(request) else ("profile" if request.user.is_authenticated else "login"))


def _mark_email_verified(user, email):
    """The person proved they own `email` by typing the code we sent to it."""
    if user.email == email and not user.email_verified:
        User.objects.filter(pk=user.pk).update(email_verified=True, email_verified_at=timezone.now())
        user.email_verified = True


def _mask_email(email):
    name, _, domain = email.partition("@")
    return f"{name[:2]}{'*' * max(len(name) - 2, 1)}@{domain}"


@login_required
@require_POST
def send_verify_email(request):
    """Email a 6-digit code to the logged-in person's own email address."""
    user = request.user
    if not user.email:
        messages.error(request, "Add an email to your account first.")
    elif user.email_verified:
        messages.info(request, "Your email is already verified.")
    elif otp.start(request, purpose="verify_email", email=user.email, name=user.name, user_id=user.pk):
        messages.success(request, f"We sent a 6-digit code to {_mask_email(user.email)}.")
        return redirect("verify_otp")
    else:
        messages.error(request, "We couldn't send the email. Please try again in a moment.")
    return redirect("profile")


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def profile_edit(request):
    """My own profile: change name, about and upload/remove my photo."""
    form = ProfileForm(request.POST or None, request.FILES or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Profile updated.")
        return redirect("profile")
    return render(request, "accounts/profile_edit.html", {"form": form})


@login_required
def profile_detail(request, user_id):
    """A friend's profile. Only people you already chat with can be viewed (plus yourself)."""
    if user_id == request.user.pk:
        return redirect("profile")
    person = get_object_or_404(User, pk=user_id)
    conversation = conversations_for(request.user).filter(
        user_a_id__in=[request.user.pk, person.pk],
        user_b_id__in=[request.user.pk, person.pk]
    ).first()
    if conversation is None:
        messages.error(request, "You can only view profiles of people you're connected with.")
        return redirect("home")
    return render(
        request,
        "accounts/profile_detail.html",
        {"person": person, "conversation": conversation}
    )


@login_required
@require_POST
def dev_notice_seen(request):
    """The welcome popup was closed: never show it to this person again."""
    User.objects.filter(pk=request.user.pk).update(seen_dev_notice=True)
    return JsonResponse({"ok": True})


@require_http_methods(["GET", "POST"])
def password_reset_request(request):
    if request.method == "POST":
        form = PasswordResetForm(request.POST)

        if form.is_valid():
            email = form.cleaned_data["email"]

            # Do not reveal whether an account exists.
            for user in form.get_users(email):
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = default_token_generator.make_token(user)

                reset_path = reverse(
                    "password_reset_confirm",
                    kwargs={"uidb64": uid, "token": token},
                )
                reset_url = request.build_absolute_uri(reset_path)

                html_content = render_to_string(
                    "accounts/password_reset_email.html",
                    {
                        "user": user,
                        "reset_url": reset_url,
                    },
                )

                text_content = render_to_string(
                    "accounts/password_reset_email.txt",
                    {
                        "user": user,
                        "reset_url": reset_url,
                    },
                )

                if not otp.send_brevo_email(
                    user.email, "Reset your Chatly password", html_content, text_content
                ):
                    logger.error("Chatly password reset email failed for user %s", user.pk)

            return redirect("password_reset_done")
    else:
        form = PasswordResetForm()

    return render(
        request,
        "accounts/password_reset.html",
        {"form": form},
    )
