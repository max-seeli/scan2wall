"""
HTTP Request Handlers Module

Handles all HTTP requests and queues jobs for the Isaac Kit main loop.
Separated from Kit processing for clarity and testability.
"""

from http.server import BaseHTTPRequestHandler
import json
import time
import uuid
import logging

logger = logging.getLogger(__name__)


class RequestHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for Isaac worker API.

    Endpoints:
    - GET  /              Health check, returns queue size
    - POST /convert       Convert GLB → USDZ with physics
    - POST /run_simulation  Run throwing simulation
    - POST /create_base_scene  Create pre-built base scene
    """

    # Class variables (set by isaac_worker.py)
    job_queue = None
    job_results = None

    def _send_json(self, status, data):
        """Send JSON response."""
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        """Handle GET requests (health check)."""
        if self.path == '/':
            self._send_json(200, {"status": "ready", "queue_size": self.job_queue.qsize()})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        """Route POST requests to appropriate handlers."""
        if self.path == '/convert':
            self._handle_convert()
        elif self.path == '/run_simulation':
            self._handle_simulation()
        elif self.path == '/create_base_scene':
            self._handle_create_base_scene()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_convert(self):
        """Handle POST /convert - Convert GLB to USDZ with physics properties."""
        try:
            req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            job_id = str(uuid.uuid4())

            convert_data = {
                'glb_path': req['glb_path'],
                'json_path': req['json_path'],
                'usd_dir': req['usd_dir']
            }
            self.job_queue.put(('convert', job_id, convert_data))
            result = self._wait_for_result(job_id)

            if result["status"] == "completed":
                logger.info(f"Conversion complete: {job_id}")
                self._send_json(200, {
                    "status": "completed",
                    "usd_dir": req['usd_dir'],
                    "usdz_path": result.get('usdz_path'),
                    "job_id": job_id
                })
            else:
                logger.error(f"Conversion failed: {job_id}")
                self._send_json(500, result)

        except Exception as e:
            logger.error(f"HTTP handler error: {e}", exc_info=True)
            self._send_json(500, {"status": "error", "error": str(e)})

    def _handle_simulation(self):
        """Handle POST /run_simulation - Run physics simulation."""
        req = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        job_id = str(uuid.uuid4())

        self.job_queue.put(('simulate', job_id, req))
        result = self._wait_for_result(job_id, timeout=300)

        status = 200 if result["status"] == "completed" else 500
        logger.info(f"Simulation {'complete' if status == 200 else 'failed'}: {job_id}")
        self._send_json(status, result)

    def _handle_create_base_scene(self):
        """Handle POST /create_base_scene - Create pre-built base scene USD."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length) if content_length > 0 else b'{}'
        req = json.loads(body) if body else {}

        output_path = req.get('output_path', '/workspace/s2w-scripts/scenes/throw_against_brick_wall.usd')
        job_id = str(uuid.uuid4())

        self.job_queue.put(('create_base_scene', job_id, {'output_path': output_path}))
        result = self._wait_for_result(job_id, timeout=60)

        status = 200 if result["status"] == "completed" else 500
        logger.info(f"Base scene {'created' if status == 200 else 'failed'}: {job_id}")
        self._send_json(status, result)

    def _wait_for_result(self, job_id, timeout=120):
        """
        Wait for job result from Kit main loop.

        Args:
            job_id: Job identifier
            timeout: Timeout in seconds

        Returns:
            Job result dictionary
        """
        start = time.time()
        while job_id not in self.job_results:
            time.sleep(0.1)
            if time.time() - start > timeout:
                return {"status": "timeout", "job_id": job_id}
        return self.job_results.pop(job_id)

    def log_message(self, format, *args):
        """Suppress default HTTP logging."""
        pass
