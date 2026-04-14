from django.core.management.base import BaseCommand

from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import Tenant, TenantAPIKey


class Command(BaseCommand):
    help = "Create a tenant API key and print it once."

    def add_arguments(self, parser):
        parser.add_argument("tenant_slug", type=str)
        parser.add_argument("--name", type=str, default="cli")

    def handle(self, *args, **options):
        tenant = Tenant.objects.get(slug=options["tenant_slug"])
        raw = generate_api_key()
        TenantAPIKey.objects.create(
            tenant=tenant,
            name=options["name"],
            key_hash=hash_api_key(raw),
        )
        self.stdout.write(self.style.WARNING("Store this key securely; it will not be shown again."))
        self.stdout.write(raw)
