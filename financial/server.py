"""Production entrypoint: drain the worker as soon as SIGTERM is received."""
import os
import uvicorn
from .main import app


class DrainingServer(uvicorn.Server):
    def handle_exit(self, sig, frame):
        app.state.draining = True
        app.state.worker.stop.set()
        super().handle_exit(sig, frame)


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    if not 1 <= port <= 65535:
        raise SystemExit('INVALID_PORT')
    DrainingServer(uvicorn.Config(app, host='0.0.0.0', port=port, access_log=False,
                                  timeout_graceful_shutdown=15)).run()
