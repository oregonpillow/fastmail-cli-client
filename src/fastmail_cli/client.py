"""JMAP client for communicating with the Fastmail API."""

from __future__ import annotations

import json
from typing import Any

import requests


class JMAPClient:
    """A JMAP client for interacting with the Fastmail API."""

    USING_CORE = "urn:ietf:params:jmap:core"
    USING_MAIL = "urn:ietf:params:jmap:mail"
    USING_SUBMISSION = "urn:ietf:params:jmap:submission"
    USING_CONTACTS = "urn:ietf:params:jmap:contacts"
    USING_MASKED_EMAIL = "https://www.fastmail.com/dev/maskedemail"

    def __init__(self, hostname: str, token: str, username: str | None = None) -> None:
        if not hostname:
            raise ValueError("hostname is required")
        if not token:
            raise ValueError("token is required")

        self.hostname = hostname
        self.token = token
        self.username = username
        self._session: dict[str, Any] | None = None
        self._api_url: str | None = None
        self._account_id: str | None = None
        self._identity_id: str | None = None

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.token}",
        }

    # ── Session ──────────────────────────────────────────────────────────

    def get_session(self) -> dict[str, Any]:
        """Fetch and cache the JMAP Session Resource."""
        if self._session is not None:
            return self._session
        r = requests.get(
            f"https://{self.hostname}/.well-known/jmap",
            headers=self._auth_headers(),
        )
        r.raise_for_status()
        self._session = r.json()
        self._api_url = self._session["apiUrl"]
        return self._session

    def get_account_id(self) -> str:
        """Return the primary mail account ID."""
        if self._account_id is not None:
            return self._account_id
        session = self.get_session()
        self._account_id = session["primaryAccounts"][self.USING_MAIL]
        return self._account_id

    def get_identity_id(self) -> str:
        """Return the identity ID matching self.username."""
        if self._identity_id is not None:
            return self._identity_id
        res = self.call(
            using=[self.USING_CORE, self.USING_SUBMISSION],
            method_calls=[
                ["Identity/get", {"accountId": self.get_account_id()}, "i"]
            ],
        )
        identities = res["methodResponses"][0][1]["list"]
        if self.username:
            identity = next(
                (i for i in identities if i["email"] == self.username), identities[0]
            )
        else:
            identity = identities[0]
        self._identity_id = str(identity["id"])
        self.username = self.username or identity["email"]
        return self._identity_id

    def call(
        self,
        using: list[str],
        method_calls: list[list[Any]],
    ) -> dict[str, Any]:
        """Make a JMAP API call and return the JSON response."""
        session = self.get_session()
        api_url = self._api_url or session["apiUrl"]
        payload = {"using": using, "methodCalls": method_calls}
        r = requests.post(
            api_url,
            headers=self._auth_headers(),
            data=json.dumps(payload),
        )
        r.raise_for_status()
        return r.json()

    # ── Mailbox helpers ──────────────────────────────────────────────────

    def get_mailboxes(self) -> list[dict[str, Any]]:
        """Return all mailboxes for the account."""
        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[
                ["Mailbox/get", {"accountId": self.get_account_id()}, "a"]
            ],
        )
        return res["methodResponses"][0][1]["list"]

    def find_mailbox_id(self, name: str | None = None, role: str | None = None) -> str:
        """Find a mailbox by name or role and return its ID."""
        filters: dict[str, Any] = {"accountId": self.get_account_id()}
        if role:
            filters["filter"] = {"role": role, "hasAnyRole": True}
        elif name:
            filters["filter"] = {"name": name}
        else:
            raise ValueError("Must specify name or role")

        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[["Mailbox/query", filters, "a"]],
        )
        ids = res["methodResponses"][0][1]["ids"]
        if not ids:
            raise ValueError(f"Mailbox not found: {name or role}")
        return ids[0]

    # ── Email helpers ────────────────────────────────────────────────────

    def list_emails(
        self,
        mailbox_id: str | None = None,
        limit: int = 10,
        properties: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """List emails, optionally filtered by mailbox."""
        if properties is None:
            properties = ["id", "subject", "from", "receivedAt", "preview"]

        query_filter: dict[str, Any] = {"accountId": self.get_account_id()}
        if mailbox_id:
            query_filter["filter"] = {"inMailbox": mailbox_id}
        query_filter["sort"] = [{"property": "receivedAt", "isAscending": False}]
        query_filter["limit"] = limit

        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[
                ["Email/query", query_filter, "a"],
                [
                    "Email/get",
                    {
                        "accountId": self.get_account_id(),
                        "properties": properties,
                        "#ids": {
                            "resultOf": "a",
                            "name": "Email/query",
                            "path": "/ids/*",
                        },
                    },
                    "b",
                ],
            ],
        )
        return res["methodResponses"][1][1]["list"]

    def read_email(self, email_id: str) -> dict[str, Any]:
        """Fetch a single email by ID with full body."""
        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[
                [
                    "Email/get",
                    {
                        "accountId": self.get_account_id(),
                        "ids": [email_id],
                        "properties": [
                            "id",
                            "subject",
                            "from",
                            "to",
                            "cc",
                            "receivedAt",
                            "textBody",
                            "htmlBody",
                            "bodyValues",
                            "preview",
                            "keywords",
                            "mailboxIds",
                        ],
                        "fetchTextBodyValues": True,
                        "fetchHTMLBodyValues": True,
                    },
                    "a",
                ]
            ],
        )
        emails = res["methodResponses"][0][1]["list"]
        if not emails:
            raise ValueError(f"Email not found: {email_id}")
        return emails[0]

    def send_email(
        self,
        to: list[dict[str, str]],
        subject: str,
        body: str,
        cc: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Compose and send an email."""
        identity_id = self.get_identity_id()
        drafts_id = self.find_mailbox_id(name="Drafts")

        draft: dict[str, Any] = {
            "from": [{"email": self.username}],
            "to": to,
            "subject": subject,
            "keywords": {"$draft": True},
            "mailboxIds": {drafts_id: True},
            "bodyValues": {"body": {"value": body, "charset": "utf-8"}},
            "textBody": [{"partId": "body", "type": "text/plain"}],
        }
        if cc:
            draft["cc"] = cc

        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL, self.USING_SUBMISSION],
            method_calls=[
                [
                    "Email/set",
                    {"accountId": self.get_account_id(), "create": {"draft": draft}},
                    "a",
                ],
                [
                    "EmailSubmission/set",
                    {
                        "accountId": self.get_account_id(),
                        "onSuccessDestroyEmail": ["#sendIt"],
                        "create": {
                            "sendIt": {
                                "emailId": "#draft",
                                "identityId": identity_id,
                            }
                        },
                    },
                    "b",
                ],
            ],
        )
        return res

    def delete_email(self, email_id: str) -> dict[str, Any]:
        """Permanently destroy an email by ID."""
        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[
                [
                    "Email/set",
                    {
                        "accountId": self.get_account_id(),
                        "destroy": [email_id],
                    },
                    "a",
                ]
            ],
        )
        return res

    def search_emails(
        self, query: str, limit: int = 10
    ) -> list[dict[str, Any]]:
        """Search emails by text query."""
        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[
                [
                    "Email/query",
                    {
                        "accountId": self.get_account_id(),
                        "filter": {"text": query},
                        "sort": [{"property": "receivedAt", "isAscending": False}],
                        "limit": limit,
                    },
                    "a",
                ],
                [
                    "Email/get",
                    {
                        "accountId": self.get_account_id(),
                        "properties": ["id", "subject", "from", "receivedAt", "preview"],
                        "#ids": {
                            "resultOf": "a",
                            "name": "Email/query",
                            "path": "/ids/*",
                        },
                    },
                    "b",
                ],
            ],
        )
        return res["methodResponses"][1][1]["list"]

    def move_email(self, email_id: str, mailbox_id: str) -> dict[str, Any]:
        """Move an email to a different mailbox."""
        # First get the current mailbox IDs to remove them
        email = self.read_email(email_id)
        current_mailbox_ids = {mid: None for mid in email.get("mailboxIds", {})}
        current_mailbox_ids[mailbox_id] = True

        res = self.call(
            using=[self.USING_CORE, self.USING_MAIL],
            method_calls=[
                [
                    "Email/set",
                    {
                        "accountId": self.get_account_id(),
                        "update": {
                            email_id: {"mailboxIds": {mailbox_id: True}},
                        },
                    },
                    "a",
                ]
            ],
        )
        return res

    # ── Masked Email helpers ─────────────────────────────────────────────

    def list_masked_emails(self) -> list[dict[str, Any]]:
        """Return all masked email addresses."""
        res = self.call(
            using=[self.USING_CORE, self.USING_MASKED_EMAIL],
            method_calls=[
                [
                    "MaskedEmail/get",
                    {"accountId": self.get_account_id(), "ids": None},
                    "a",
                ]
            ],
        )
        return res["methodResponses"][0][1]["list"]

    def create_masked_email(
        self,
        for_domain: str | None = None,
        description: str | None = None,
        prefix: str | None = None,
        state: str = "enabled",
    ) -> dict[str, Any]:
        """Create a new masked email address."""
        masked: dict[str, Any] = {"state": state}
        if for_domain:
            masked["forDomain"] = for_domain
        if description:
            masked["description"] = description
        if prefix:
            masked["emailPrefix"] = prefix

        res = self.call(
            using=[self.USING_CORE, self.USING_MASKED_EMAIL],
            method_calls=[
                [
                    "MaskedEmail/set",
                    {
                        "accountId": self.get_account_id(),
                        "create": {"me": masked},
                    },
                    "a",
                ]
            ],
        )
        return res["methodResponses"][0][1]["created"]["me"]

    def update_masked_email(
        self,
        masked_email_id: str,
        state: str | None = None,
        for_domain: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        """Update a masked email address."""
        updates: dict[str, Any] = {}
        if state is not None:
            updates["state"] = state
        if for_domain is not None:
            updates["forDomain"] = for_domain
        if description is not None:
            updates["description"] = description

        res = self.call(
            using=[self.USING_CORE, self.USING_MASKED_EMAIL],
            method_calls=[
                [
                    "MaskedEmail/set",
                    {
                        "accountId": self.get_account_id(),
                        "update": {masked_email_id: updates},
                    },
                    "a",
                ]
            ],
        )
        return res

    def delete_masked_email(self, masked_email_id: str) -> dict[str, Any]:
        """Delete (disable) a masked email address by setting state to 'deleted'."""
        return self.update_masked_email(masked_email_id, state="deleted")
