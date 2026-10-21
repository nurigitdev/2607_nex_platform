from .app import SERVICE_SPEC, create_eos_app

app = create_eos_app()

__all__ = ("SERVICE_SPEC", "app", "create_eos_app")
