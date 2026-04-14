from celery import shared_task

from apps.workflows.services.workflow_engine import process_due_executions


@shared_task
def process_workflow_due_steps():
    return process_due_executions()
