from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.core"
    verbose_name = "Core"

    def ready(self) -> None:
        # Before apps that `from django.shortcuts import redirect` load (e.g. apps.ui), patch
        # Django 5.2.13 redirect()/HttpResponseRedirect preserve_request mismatch.
        from apps.core.django_redirect_compat import apply_redirect_patch_if_needed

        apply_redirect_patch_if_needed()
