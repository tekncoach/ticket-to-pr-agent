# tools/http_client.py
import httpx, time, hashlib, json
from agent.runtime import ToolResult

class ResilientClient:
    def __init__(self, base_url: str, token: str, timeout: float = 15.0):
        self.base_url = base_url
        self.headers = {"Authorization": f"Bearer {token}"}
        self.timeout = timeout

    def request(self, method: str, path: str, **kwargs) -> ToolResult:
        for attempt in range(4):
            try:
                with httpx.Client(timeout=self.timeout) as c:
                    r = c.request(method, f"{self.base_url}{path}", headers=self.headers, **kwargs)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                if r.status_code == 401:
                    return ToolResult(False, error_code="AUTH")
                if r.status_code == 404:
                    return ToolResult(False, error_code="NOT_FOUND")
                if r.status_code >= 400:
                    return ToolResult(False, error_code="VALIDATION", data=r.text[:500])
                return ToolResult(True, data=r.json() if r.content else None)
            except httpx.TimeoutException:
                if attempt == 3:
                    return ToolResult(False, error_code="TIMEOUT")
                time.sleep(0.5 * (2 ** attempt))
            except httpx.HTTPError as e:
                return ToolResult(False, error_code="NETWORK", data=str(e))
        return ToolResult(False, error_code="RATE_LIMIT")

def idempotency_key(user_id: str, action: str, payload: dict) -> str:
    raw = json.dumps({"u": user_id, "a": action, "p": payload}, sort_keys=True)
    return hashlib.sha256(raw.encode()).hexdigest()[:32]
