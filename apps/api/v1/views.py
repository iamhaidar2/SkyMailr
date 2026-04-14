from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.api.authentication import ApiTenantUser
from apps.api.permissions import HasTenant
from apps.email_templates.models import (
    ApprovalStatus,
    EmailTemplate,
    EmailTemplateVersion,
    TemplateRenderLog,
    TemplateStatus,
)
from apps.email_templates.services.llm_service import TemplateLLMService
from apps.email_templates.services.render_service import render_email_version, TemplateRenderError
from apps.email_templates.services.validation_service import TemplateValidationService
from apps.llm.schemas import TemplateGenerationBriefSchema
from apps.messages.models import IdempotencyKeyRecord, OutboundMessage, OutboundStatus
from apps.messages.services.idempotency import hash_idempotency_key
from apps.messages.services.send_pipeline import create_raw_message, create_templated_message
from apps.messages.tasks import dispatch_message_task
from apps.providers.registry import get_email_provider
from apps.providers.webhook_service import ProviderWebhookService
from apps.subscriptions.models import UnsubscribeRecord
from apps.tenants.crypto import generate_api_key, hash_api_key
from apps.tenants.models import Tenant, TenantAPIKey
from apps.workflows.models import Workflow, WorkflowEnrollment
from apps.workflows.services.workflow_engine import enroll_workflow

from .serializers import (
    ApproveVersionSerializer,
    EmailTemplateSerializer,
    OutboundMessageSerializer,
    PreviewSerializer,
    SendRawSerializer,
    SendTemplateSerializer,
    TemplateGenerateSerializer,
    TemplateReviseSerializer,
    UnsubscribeSerializer,
    WorkflowEnrollSerializer,
)


def _tenant(request):
    u = request.user
    if isinstance(u, ApiTenantUser):
        return u.tenant
    return None


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "time": timezone.now().isoformat()})


class ProviderHealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        p = get_email_provider()
        ok, detail = p.health_check()
        return Response({"provider": p.name, "ok": ok, "detail": detail})


class SendTemplateView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request):
        ser = SendTemplateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        tenant = _tenant(request)
        tpl = get_object_or_404(
            EmailTemplate, tenant=tenant, key=data["template_key"]
        )
        raw_idem = (data.get("idempotency_key") or "").strip()
        if raw_idem:
            h = hash_idempotency_key(str(tenant.id), raw_idem)
            existing = IdempotencyKeyRecord.objects.filter(
                tenant=tenant, key_hash=h
            ).first()
            if existing:
                return Response(
                    OutboundMessageSerializer(existing.message).data,
                    status=status.HTTP_200_OK,
                )
        try:
            msg = create_templated_message(
                tenant=tenant,
                template=tpl,
                source_app=data["source_app"],
                message_type=data["message_type"],
                to_email=data["to_email"],
                to_name=data.get("to_name") or "",
                context=data["context"],
                metadata=data.get("metadata"),
                tags=data.get("tags"),
                idempotency_key=raw_idem or None,
                scheduled_for=data.get("scheduled_for"),
            )
        except ValueError as e:
            return Response({"detail": str(e)}, status=400)
        if raw_idem and msg.status != OutboundStatus.SUPPRESSED:
            IdempotencyKeyRecord.objects.get_or_create(
                tenant=tenant,
                key_hash=hash_idempotency_key(str(tenant.id), raw_idem),
                defaults={"message": msg},
            )
        if msg.status == OutboundStatus.QUEUED:
            dispatch_message_task.delay(str(msg.id))
        return Response(OutboundMessageSerializer(msg).data, status=201)


class SendRawView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request):
        ser = SendRawSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        tenant = _tenant(request)
        raw_idem = (d.get("idempotency_key") or "").strip()
        if raw_idem:
            h = hash_idempotency_key(str(tenant.id), raw_idem)
            existing = IdempotencyKeyRecord.objects.filter(
                tenant=tenant, key_hash=h
            ).first()
            if existing:
                return Response(
                    OutboundMessageSerializer(existing.message).data,
                    status=200,
                )
        msg = create_raw_message(
            tenant=tenant,
            source_app=d["source_app"],
            message_type=d["message_type"],
            to_email=d["to_email"],
            to_name=d.get("to_name") or "",
            subject=d["subject"],
            html_body=d["html_body"],
            text_body=d.get("text_body") or "",
            metadata=d.get("metadata"),
            idempotency_key=raw_idem or None,
        )
        if raw_idem and msg.status != OutboundStatus.SUPPRESSED:
            IdempotencyKeyRecord.objects.get_or_create(
                tenant=tenant,
                key_hash=hash_idempotency_key(str(tenant.id), raw_idem),
                defaults={"message": msg},
            )
        if msg.status == OutboundStatus.QUEUED:
            dispatch_message_task.delay(str(msg.id))
        return Response(OutboundMessageSerializer(msg).data, status=201)


class MessageDetailView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def get(self, request, uuid):
        tenant = _tenant(request)
        msg = get_object_or_404(OutboundMessage, pk=uuid, tenant=tenant)
        return Response(OutboundMessageSerializer(msg).data)


class MessageRetryView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request, uuid):
        tenant = _tenant(request)
        msg = get_object_or_404(OutboundMessage, pk=uuid, tenant=tenant)
        if msg.status not in (OutboundStatus.FAILED, OutboundStatus.DEFERRED):
            return Response({"detail": "Not retryable"}, status=400)
        msg.status = OutboundStatus.QUEUED
        msg.next_retry_at = None
        msg.save(update_fields=["status", "next_retry_at", "updated_at"])
        dispatch_message_task.delay(str(msg.id))
        return Response(OutboundMessageSerializer(msg).data)


class MessageCancelView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request, uuid):
        tenant = _tenant(request)
        msg = get_object_or_404(OutboundMessage, pk=uuid, tenant=tenant)
        if msg.status not in (
            OutboundStatus.QUEUED,
            OutboundStatus.RENDERED,
            OutboundStatus.DEFERRED,
        ):
            return Response({"detail": "Cannot cancel"}, status=400)
        msg.status = OutboundStatus.CANCELLED
        msg.save(update_fields=["status", "updated_at"])
        return Response({"status": "cancelled"})


class TemplateListView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def get(self, request):
        tenant = _tenant(request)
        qs = EmailTemplate.objects.filter(tenant=tenant)
        return Response(EmailTemplateSerializer(qs, many=True).data)


class TemplateGenerateView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request):
        ser = TemplateGenerateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        tenant = _tenant(request)
        tpl, _ = EmailTemplate.objects.get_or_create(
            tenant=tenant,
            key=d["template_key"],
            defaults={
                "name": d["name"],
                "category": d["category"],
                "status": TemplateStatus.DRAFT,
            },
        )
        brief = TemplateGenerationBriefSchema.model_validate(d["brief"])
        try:
            version = TemplateLLMService().generate_draft_version(
                template=tpl, brief=brief
            )
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"template_id": str(tpl.id), "version_id": str(version.id)})


class TemplateReviseView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request, template_id):
        tenant = _tenant(request)
        tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant=tenant)
        ser = TemplateReviseSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ver = tpl.versions.order_by("-version_number").first()
        if not ver:
            return Response({"detail": "No version"}, status=400)
        try:
            new_ver = TemplateLLMService().revise_template_version(
                template=tpl, base_version=ver, instructions=ser.validated_data["instructions"]
            )
        except Exception as e:
            return Response({"detail": str(e)}, status=400)
        return Response({"version_id": str(new_ver.id)})


class TemplateApproveView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request, template_id):
        tenant = _tenant(request)
        tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant=tenant)
        ser = ApproveVersionSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ver = tpl.versions.order_by("-version_number").first()
        if not ver:
            return Response({"detail": "No version"}, status=400)
        EmailTemplateVersion.objects.filter(template=tpl).update(is_current_approved=False)
        ver.approval_status = ApprovalStatus.APPROVED
        ver.approved_at = timezone.now()
        ver.is_current_approved = True
        ver.save(update_fields=["approval_status", "approved_at", "is_current_approved"])
        tpl.status = TemplateStatus.ACTIVE
        tpl.save(update_fields=["status", "updated_at"])
        return Response({"approved_version": str(ver.id)})


class TemplatePreviewView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request, template_id):
        tenant = _tenant(request)
        tpl = get_object_or_404(EmailTemplate, pk=template_id, tenant=tenant)
        ser = PreviewSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        ver = tpl.versions.order_by("-version_number").first()
        if not ver:
            return Response({"detail": "No version"}, status=400)
        ctx = ser.validated_data.get("context") or {}
        try:
            TemplateValidationService.validate_context(tpl, ctx)
            out = render_email_version(
                subject_template=ver.subject_template,
                preview_template=ver.preview_text_template,
                html_template=ver.html_template,
                text_template=ver.text_template,
                context=ctx,
                sanitize=True,
            )
        except (TemplateRenderError, ValueError) as e:
            return Response({"detail": str(e)}, status=400)
        TemplateRenderLog.objects.create(
            template_version=ver,
            context_snapshot=ctx,
            subject_rendered=out["subject"],
            html_rendered=out["html"],
            text_rendered=out["text"],
            success=True,
        )
        return Response(out)


class WorkflowCreateView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request):
        tenant = _tenant(request)
        name = request.data.get("name", "Workflow")
        slug = request.data.get("slug")
        if not slug:
            return Response({"detail": "slug required"}, status=400)
        wf, _ = Workflow.objects.get_or_create(
            tenant=tenant, slug=slug, defaults={"name": name}
        )
        return Response({"id": str(wf.id), "slug": wf.slug})


class WorkflowEnrollView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def post(self, request, workflow_id):
        tenant = _tenant(request)
        ser = WorkflowEnrollSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        wf = get_object_or_404(Workflow, pk=workflow_id, tenant=tenant)
        en = WorkflowEnrollment.objects.create(
            tenant=tenant,
            workflow=wf,
            recipient_email=d["recipient_email"],
            recipient_name=d.get("recipient_name") or "",
            external_user_id=d.get("external_user_id") or "",
            metadata=d.get("metadata") or {},
        )
        ex = enroll_workflow(enrollment=en)
        return Response({"enrollment_id": str(en.id), "execution_id": str(ex.id)})


class UnsubscribeView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        ser = UnsubscribeSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        d = ser.validated_data
        tenant_slug = request.data.get("tenant_slug")
        if not tenant_slug:
            return Response({"detail": "tenant_slug required"}, status=400)
        tenant = get_object_or_404(Tenant, slug=tenant_slug)
        UnsubscribeRecord.objects.update_or_create(
            tenant=tenant,
            email=d["email"],
            channel=d.get("channel") or "marketing",
            defaults={"source": "api", "metadata": {}},
        )
        return Response({"status": "ok"})


class ProviderWebhookView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request, provider):
        raw = request.body
        headers = {k: v for k, v in request.headers.items()}
        svc = ProviderWebhookService()
        ev = svc.ingest(provider=provider, raw_body=raw, headers=headers)
        return Response({"id": str(ev.id), "signature_valid": ev.signature_valid})


class CreateApiKeyView(APIView):
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request):
        slug = request.data.get("tenant_slug")
        name = request.data.get("name", "default")
        if not slug:
            return Response({"detail": "tenant_slug required"}, status=400)
        tenant = get_object_or_404(Tenant, slug=slug)
        raw = generate_api_key()
        TenantAPIKey.objects.create(
            tenant=tenant,
            name=name,
            key_hash=hash_api_key(raw),
        )
        return Response({"api_key": raw, "warning": "Store once; not shown again."})


class SuppressionListView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def get(self, request):
        from apps.subscriptions.models import DeliverySuppression

        tenant = _tenant(request)
        qs = DeliverySuppression.objects.filter(tenant=tenant)[:200]
        return Response(
            [
                {
                    "email": s.email,
                    "reason": s.reason,
                    "created_at": s.created_at.isoformat(),
                }
                for s in qs
            ]
        )


class MessageEventsView(APIView):
    permission_classes = [IsAuthenticated, HasTenant]

    def get(self, request, uuid):
        tenant = _tenant(request)
        msg = get_object_or_404(OutboundMessage, pk=uuid, tenant=tenant)
        evs = msg.events.order_by("created_at")
        return Response(
            [
                {"type": e.event_type, "payload": e.payload, "at": e.created_at.isoformat()}
                for e in evs
            ]
        )
