from fastapi.middleware.cors import CORSMiddleware
def add_cors_middleware(app):
    origins = [
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "*"
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
