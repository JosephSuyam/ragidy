"""Upload a document in the browser, ask about it, reload, then delete what was created."""

import os
from typing import TYPE_CHECKING

import pytest
from ollama_stub import ANSWER

if TYPE_CHECKING:
    from playwright.sync_api import Page

pytestmark = pytest.mark.skipif(
    not os.environ.get("E2E_BASE_URL"), reason="E2E_BASE_URL is not set; start the e2e stack first"
)

DOCUMENT = b"Uploads are stored in object storage.\n"
DOCUMENT_NAME = "e2e.txt"
QUESTION = "Where are uploads stored?"
READY_TIMEOUT_MS = 60_000
ANSWER_TIMEOUT_MS = 30_000


def test_upload_ask_and_delete(stack: str, page: "Page") -> None:
    from playwright.sync_api import expect

    page.goto("/")
    page.get_by_label("Upload a file").set_input_files(
        {"name": DOCUMENT_NAME, "mimeType": "text/plain", "buffer": DOCUMENT}
    )
    page.get_by_role("button", name="Upload", exact=True).click()
    document = (
        page.get_by_role("list", name="Document list")
        .get_by_role("listitem")
        .filter(has_text=DOCUMENT_NAME)
    )
    expect(document.get_by_text("ready", exact=True)).to_be_visible(timeout=READY_TIMEOUT_MS)

    page.get_by_label("Message", exact=True).fill(QUESTION)
    page.get_by_role("button", name="Send", exact=True).click()
    log = page.get_by_role("log", name="Messages")
    expect(log).to_have_attribute("aria-busy", "false", timeout=ANSWER_TIMEOUT_MS)
    # Exact: the stub answer is the document text, so a substring match would pass on the citation.
    expect(log.get_by_text(ANSWER, exact=True)).to_be_visible()
    expect(log.get_by_role("list", name="Sources")).to_contain_text(DOCUMENT_NAME)

    page.reload()
    chat_list = page.get_by_role("list", name="Chat list")
    chat_list.get_by_role("button", name=QUESTION, exact=True).click()
    expect(log.get_by_text(ANSWER, exact=True)).to_be_visible()
    expect(log.get_by_role("list", name="Sources")).to_contain_text(DOCUMENT_NAME)

    # Delete buttons confirm with window.confirm, which Playwright dismisses unless accepted.
    page.on("dialog", lambda dialog: dialog.accept())
    page.get_by_role("button", name=f"Delete {QUESTION}").click()
    expect(page.get_by_text("No chats yet")).to_be_visible()
    page.get_by_role("button", name=f"Delete {DOCUMENT_NAME}").click()
    expect(page.get_by_text("No documents yet")).to_be_visible()
