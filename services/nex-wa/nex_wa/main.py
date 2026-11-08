from .app import SERVICE_SPEC, create_wa_app

app = create_wa_app()

__all__ = ("SERVICE_SPEC", "app", "create_wa_app")
