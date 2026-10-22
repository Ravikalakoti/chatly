from django import forms
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password

from .utils import parse_identifier

User = get_user_model()


class StyledForm(forms.Form):
    """Adds the CSS class our stylesheet expects to every input."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "input")



class SignupForm(StyledForm):
    display_name = forms.CharField(
        label="Your name",
        max_length=60,
        widget=forms.TextInput(
            attrs={
                "placeholder": "e.g. Ravi",
                "autocomplete": "name",
            }
        ),
    )

    identifier = forms.CharField(
        label="Phone number or email",
        max_length=254,
        widget=forms.TextInput(
            attrs={
                "placeholder": "98765 43210 or you@example.com",
                "autocomplete": "username",
            }
        ),
    )

    date_of_birth = forms.DateField(
        label="Date of Birth",
        widget=forms.DateInput(
            attrs={"type": "date"}
        ),
    )

    gender = forms.ChoiceField(
        label="Gender",
        choices=[
            ("", "Select gender"),
            ("male", "Male"),
            ("female", "Female"),
            ("other", "Other"),
        ],
        widget=forms.Select(),
    )

    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password"}
        ),
    )

    password2 = forms.CharField(
        label="Confirm password",
        widget=forms.PasswordInput(
            attrs={"autocomplete": "new-password"}
        ),
    )

    def clean_display_name(self):
        name = " ".join(self.cleaned_data["display_name"].split())
        if not name:
            raise forms.ValidationError("Please enter your name.")
        return name

    def clean_identifier(self):
        kind, value = parse_identifier(
            self.cleaned_data["identifier"]
        )

        if not kind:
            raise forms.ValidationError(
                "Enter a valid phone number or email address."
            )

        if User.objects.filter(**{kind: value}).exists():
            label = "email" if kind == "email" else "phone number"
            raise forms.ValidationError(
                f"An account with this {label} already exists. Try logging in."
            )

        self._kind, self._value = kind, value
        return value

    def clean(self):
        cleaned = super().clean()
        p1 = cleaned.get("password1")
        p2 = cleaned.get("password2")

        if p1 and p2:
            if p1 != p2:
                self.add_error(
                    "password2",
                    "The two passwords don't match."
                )
            else:
                try:
                    validate_password(p1)
                except forms.ValidationError as exc:
                    self.add_error("password1", exc)

        return cleaned

    def save(self, commit=True):
        user = User(
            display_name=self.cleaned_data["display_name"],
            date_of_birth=self.cleaned_data["date_of_birth"],
            gender=self.cleaned_data["gender"],
        )

        setattr(user, self._kind, self._value)
        user.set_password(self.cleaned_data["password1"])

        if commit:
            user.save()

        return user


class LoginForm(StyledForm):
    identifier = forms.CharField(
        label="Phone number or email",
        max_length=254,
        widget=forms.TextInput(
            attrs={"placeholder": "98765 43210 or you@example.com", "autocomplete": "username", "inputmode": "email"}
        ),
    )
    password = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )

    def __init__(self, request=None, *args, **kwargs):
        self.request = request
        self.user = None
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        identifier, password = cleaned.get("identifier"), cleaned.get("password")
        if identifier and password:
            self.user = authenticate(self.request, username=identifier.strip(), password=password)
            if self.user is None:
                raise forms.ValidationError("Incorrect phone/email or password.")
        return cleaned



class OtpForm(StyledForm):
    code = forms.CharField(
        label="6-digit code",
        min_length=6,
        max_length=6,
        widget=forms.TextInput(
            attrs={
                "inputmode": "numeric",
                "autocomplete": "one-time-code",
                "pattern": "[0-9]{6}",
                "maxlength": "6",
                "placeholder": "••••••",
                "autofocus": "autofocus",
                "class": "input otp-input",
            }
        ),
    )

    def clean_code(self):
        code = self.cleaned_data["code"].strip()
        if not code.isdigit():
            raise forms.ValidationError("Enter the 6-digit code from your email.")
        return code


class ProfileForm(forms.ModelForm):
    """Edit my profile: name, DOB, gender, about line and profile photo."""

    MAX_PHOTO_MB = 5
    remove_avatar = forms.BooleanField(
        required=False,
        label="Remove my photo",
    )

    class Meta:
        model = User
        fields = [
            "display_name",
            "date_of_birth",
            "gender",
            "about",
            "avatar",
        ]
        labels = {
            "display_name": "Your name",
            "date_of_birth": "Date of Birth",
            "gender": "Gender",
            "about": "About",
            "avatar": "Profile photo",
        }
        widgets = {
            "display_name": forms.TextInput(
                attrs={"class": "input"}
            ),
            "date_of_birth": forms.DateInput(
                attrs={
                    "class": "input",
                    "type": "date",
                }
            ),
            "gender": forms.Select(
                attrs={"class": "input"}
            ),
            "about": forms.TextInput(
                attrs={
                    "class": "input",
                    "placeholder": "Hey there! I am using Chatly.",
                }
            ),
            "avatar": forms.FileInput(
                attrs={
                    "accept": "image/*",
                    "id": "avatar-input",
                }
            ),
        }

    def clean_display_name(self):
        name = " ".join(
            self.cleaned_data["display_name"].split()
        )
        if not name:
            raise forms.ValidationError(
                "Please enter your name."
            )
        return name

    def clean_avatar(self):
        photo = self.cleaned_data.get("avatar")

        # Validate only a newly uploaded file.
        if photo and hasattr(photo, "content_type"):
            if photo.size > self.MAX_PHOTO_MB * 1024 * 1024:
                raise forms.ValidationError(
                    f"Photo must be smaller than {self.MAX_PHOTO_MB} MB."
                )

        return photo

    def save(self, commit=True):
        user = super().save(commit=False)

        if (
            self.cleaned_data.get("remove_avatar")
            and not self.files.get("avatar")
        ):
            user.avatar = ""

        if commit:
            user.save()

        return user
