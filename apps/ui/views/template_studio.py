from django.contrib import messages as django_messages
from django.shortcuts import redirect, render

from apps.email_templates.models import EmailTemplate, TemplateStatus
from apps.email_templates.services.llm_service import TemplateLLMService
from apps.llm.schemas import TemplateGenerationBriefSchema
from apps.ui.context import operator_shell_context
from apps.ui.decorators import operator_required
from apps.ui.forms import TemplateStudioBriefForm
from apps.ui.services.operator import get_active_tenant


@operator_required
def template_studio(request):
    tenant = get_active_tenant(request)
    form = TemplateStudioBriefForm()
    ctx = operator_shell_context(request)
    ctx.update(
        {
            "page_title": "Template studio",
            "nav_active": "studio",
            "form": form,
            "no_tenant": tenant is None,
        }
    )
    if request.method == "POST":
        form = TemplateStudioBriefForm(request.POST)
        if not tenant:
            django_messages.error(request, "Select an active tenant.")
            return render(request, "ui/pages/template_studio.html", ctx, status=400)
        if form.is_valid():
            d = form.cleaned_data
            tpl, _ = EmailTemplate.objects.get_or_create(
                tenant=tenant,
                key=d["template_key"],
                defaults={
                    "name": d["name"],
                    "category": d["category"],
                    "status": TemplateStatus.DRAFT,
                },
            )
            brief = TemplateGenerationBriefSchema.model_validate(form.brief_dict())
            try:
                TemplateLLMService().generate_draft_version(template=tpl, brief=brief)
            except Exception as e:
                django_messages.error(request, str(e))
                ctx["form"] = form
                return render(request, "ui/pages/template_studio.html", ctx, status=400)
            django_messages.success(request, "Draft generated. Review and approve in Templates.")
            return redirect("ui:template_detail", template_id=tpl.id)
        ctx["form"] = form
        return render(request, "ui/pages/template_studio.html", ctx, status=400)
    return render(request, "ui/pages/template_studio.html", ctx)
