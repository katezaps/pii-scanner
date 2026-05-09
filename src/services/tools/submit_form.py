"""submit_form tool — submits a search form and checks for PII matches."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from agents import function_tool
from playwright.async_api import BrowserContext
from playwright.async_api import TimeoutError as PlaywrightTimeout

from src.services.browser import new_page
from src.services.tools.pii import check_pii_in_body

_DEFAULT_PAGE_TIMEOUT_MS = 30_000


def make_submit_form_tool(
    ctx: BrowserContext,
    identity: dict[str, str],
    timeout_ms: int = _DEFAULT_PAGE_TIMEOUT_MS,
    partial_results: dict[str, bool] | None = None,
):
    """Create a submit_form tool that checks results for PII matches internally.

    The tool submits the search form, scans the rendered response body for the
    user's PII values, and returns only metadata + match results. The response
    body is never returned — it stays in-process and is discarded after matching.
    """

    @function_tool
    async def submit_form(url: str, method: str, params: str) -> str:
        """Submit a search form to a broker site and check if the user's
        identity data appears in the results.

        Args:
            url: The form action URL to submit to.
            method: HTTP method — "GET" or "POST".
            params: JSON-encoded dict of form field names to values.
        """
        try:
            form_data = json.loads(params)
        except (json.JSONDecodeError, TypeError):
            return json.dumps({"error": "Invalid params JSON"})

        try:
            async with new_page(ctx, timeout_ms=timeout_ms) as page:
                if method.upper() == "POST":
                    await page.goto(url, wait_until="domcontentloaded")
                    async with page.expect_navigation(
                        wait_until="networkidle",
                    ):
                        await page.evaluate(
                            """(data) => {
                            const form = document.createElement('form');
                            form.method = 'POST';
                            form.action = data.url;
                            for (const [k, v] of Object.entries(data.params)) {
                                const input = document.createElement('input');
                                input.type = 'hidden';
                                input.name = k;
                                input.value = String(v);
                                form.appendChild(input);
                            }
                            document.body.appendChild(form);
                            form.submit();
                        }""",
                            {"url": url, "params": form_data},
                        )
                    status_code = 200
                    final_url = page.url
                else:
                    parsed = urlparse(url)
                    qs = parse_qs(parsed.query)
                    qs.update({k: [v] for k, v in form_data.items()})
                    full_url = urlunparse(parsed._replace(query=urlencode(qs, doseq=True)))
                    response = await page.goto(full_url, wait_until="networkidle")
                    status_code = response.status if response else 0
                    final_url = page.url

                body = await page.content()
                pii_detected = check_pii_in_body(body, identity)

                if partial_results is not None:
                    for field_type, found in pii_detected.items():
                        if found or field_type not in partial_results:
                            partial_results[field_type] = found

                return json.dumps(
                    {
                        "status_code": status_code,
                        "content_length": len(body),
                        "final_url": final_url,
                        "pii_detected": pii_detected,
                    }
                )
        except PlaywrightTimeout:
            return json.dumps({"error": "Page navigation timed out"})
        except Exception as e:
            return json.dumps({"error": type(e).__name__})

    return submit_form
