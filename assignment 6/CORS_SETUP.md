# CORS Setup — Required for all FastAPI services

Add this to **each** of the 4 FastAPI services (pipeline_controller, failure_classifier, recovery_manager, notification_service) right after `app = FastAPI(...)`:

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Then install if needed:
```bash
pip install "fastapi[all]"
```

Without this, your browser will block API calls from the React UI.
