from django.conf import settings
import requests
from django.contrib import messages
from django.http import JsonResponse
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

from .forms import LoginForm, SignupForm, ProfileForm
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
        user = form.save()
        return _finish_auth(request, user) or redirect("home")
    return render(request, "accounts/signup.html", {"form": form, "inviter": inviter})


def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")

    inviter = _inviter_from_code(request.session.get(INVITE_SESSION_KEY))
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    form = LoginForm(request, request.POST or None)
    if request.method == "POST" and form.is_valid():
        response = _finish_auth(request, form.user)
        if response:
            return response
        if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
            return redirect(next_url)
        return redirect("home")
    return render(request, "accounts/login.html", {"form": form, "inviter": inviter, "next": next_url})


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

                payload = {
                    "sender": {
                        "name": "Chatly",
                        "email": settings.DEFAULT_FROM_EMAIL,
                    },
                    "to": [{"email": user.email}],
                    "subject": "Reset your Chatly password",
                    "htmlContent": html_content,
                    "textContent": text_content,
                }
       
                try:
                    response = requests.post(
                        "https://api.brevo.com/v3/smtp/email",
                        headers={
                            "accept": "application/json",
                            "api-key": "settings.BREVO_API_KEY",
                            "content-type": "application/json",
                        },
                        json=payload,
                        timeout=15,
                    )
                    response.raise_for_status()
                except (requests.RequestException, AttributeError):
                    logger.exception("Chatly password reset email failed")

            return redirect("password_reset_done")
    else:
        form = PasswordResetForm()

    return render(
        request,
        "accounts/password_reset.html",
        {"form": form},
    )

