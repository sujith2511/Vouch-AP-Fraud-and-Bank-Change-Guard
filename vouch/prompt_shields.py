"""Azure AI Content Safety Prompt Shields: screens the untrusted vendor email for injected instructions before the model
reads it. The email is sent as a *document* (indirect / document attack detection), not as the user prompt.

Optional: without AZURE_CONTENT_SAFETY_ENDPOINT + AZURE_CONTENT_SAFETY_KEY it returns status 'not_configured' and the
agent runs as before. A detection can only make the agent's verdict stricter (see LLMAgent._guard); a failed or
skipped scan never makes anything looser.

Docs: https://learn.microsoft.com/azure/ai-services/content-safety/quickstart-jailbreak
"""
import os

API_VERSION = "2024-09-01"
CHUNK = 10_000      # characters per document; long emails are split across documents, never truncated
TASK_PROMPT = "Investigate this vendor email for accounts-payable fraud."


def is_configured():
    return bool(os.environ.get("AZURE_CONTENT_SAFETY_ENDPOINT") and os.environ.get("AZURE_CONTENT_SAFETY_KEY"))


def shield_email(subject, body, post=None, timeout=10.0):
    """Returns {"status": "ok"|"not_configured"|"error", "provider": "azure_prompt_shields", "attack_detected": bool|None, ...}.
    `post(url, headers, json) -> dict` is injectable for tests; the default uses httpx."""
    out = {"provider": "azure_prompt_shields", "attack_detected": None}
    if not is_configured():
        return {**out, "status": "not_configured"}
    text = f"Subject: {subject or ''}\n\n{body or ''}"
    docs = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)] or [""]
    url = os.environ["AZURE_CONTENT_SAFETY_ENDPOINT"].rstrip("/") + f"/contentsafety/text:shieldPrompt?api-version={API_VERSION}"
    headers = {"Ocp-Apim-Subscription-Key": os.environ["AZURE_CONTENT_SAFETY_KEY"], "Content-Type": "application/json"}
    try:
        data = (post or _httpx_post)(url, headers, {"userPrompt": TASK_PROMPT, "documents": docs}, timeout)
        flags = [bool(d.get("attackDetected")) for d in data.get("documentsAnalysis", [])]
        if len(flags) != len(docs):
            return {**out, "status": "error", "error": "unexpected response shape"}
        return {**out, "status": "ok", "attack_detected": any(flags), "documents": len(docs)}
    except Exception as ex:   # a scan failure is recorded, never fatal
        return {**out, "status": "error", "error": f"{type(ex).__name__}: {str(ex)[:200]}"}


def _httpx_post(url, headers, payload, timeout):
    import httpx
    r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()
