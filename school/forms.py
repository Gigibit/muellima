from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from .models import UserProfile


class EmailAuthenticationForm(AuthenticationForm):
    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autocomplete": "email", "autofocus": True}),
    )
    password = forms.CharField(
        label="Password",
        strip=False,
        widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}),
    )


class RegistrationForm(forms.Form):
    first_name = forms.CharField(label="Nome", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "given-name"}))
    last_name = forms.CharField(label="Cognome", max_length=150, widget=forms.TextInput(attrs={"autocomplete": "family-name"}))
    email = forms.EmailField(label="Email", widget=forms.EmailInput(attrs={"autocomplete": "email"}))
    password = forms.CharField(label="Password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password_confirm = forms.CharField(label="Conferma password", strip=False, widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean_email(self):
        email = self.cleaned_data["email"].strip().casefold()
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Esiste già un account con questa email.")
        return email

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password and password != cleaned.get("password_confirm"):
            self.add_error("password_confirm", "Le password non coincidono.")
        if password:
            try:
                validate_password(password)
            except ValidationError as error:
                self.add_error("password", error)
        return cleaned

    def save(self):
        return get_user_model().objects.create_user(
            username=self.cleaned_data["email"],
            email=self.cleaned_data["email"],
            first_name=self.cleaned_data["first_name"].strip(),
            last_name=self.cleaned_data["last_name"].strip(),
            password=self.cleaned_data["password"],
        )


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ("display_name", "realtime_reasoning_effort", "learning_context")
        labels = {
            "display_name": "Nome",
            "realtime_reasoning_effort": "Livello di ragionamento",
            "learning_context": "Contesto per il professore",
        }
        help_texts = {
            "realtime_reasoning_effort": (
                "Livelli più alti possono aumentare qualità, latenza e consumo di token."
            ),
            "learning_context": (
                "Massimo 100 parole. Esempio: Parlami come se fossi un bambino di 8 anni."
            ),
        }
        widgets = {
            "display_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "learning_context": forms.Textarea(attrs={"rows": 5, "data-word-limit": "100"}),
        }
