from django import forms

from .models import UserProfile


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
