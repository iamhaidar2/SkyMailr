from rest_framework.views import exception_handler as drf_exception_handler


def custom_exception_handler(exc, context):
    return drf_exception_handler(exc, context)
