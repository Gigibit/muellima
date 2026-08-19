from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Subscription, UserProfile


def default_display_name(user) -> str:
    full_name = user.get_full_name().strip()
    if full_name:
        return full_name
    if user.email:
        return user.email.split("@", 1)[0]
    return user.get_username()


@receiver(post_save, sender=get_user_model())
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(
            user=instance,
            defaults={"display_name": default_display_name(instance)},
        )
        Subscription.objects.get_or_create(user=instance)
