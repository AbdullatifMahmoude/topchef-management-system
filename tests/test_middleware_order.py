from app.main import app


def test_observability_wraps_error_handler_and_auth():
    middleware_names = [item.cls.__name__ for item in app.user_middleware]
    assert middleware_names.index("ObservabilityMiddleware") < middleware_names.index("ErrorHandlerMiddleware")
    assert middleware_names.index("ErrorHandlerMiddleware") < middleware_names.index("AuthMiddleware")
