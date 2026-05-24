# Fastmail CLI Client

<div align="center">
  <img src="logo.png" width="400px" alt="Logo" />
  <h1 style="font-size: 28px; margin: 10px 0;"></h1>
  <p>A command-line tool for interacting with the Fastmail JMAP API.</p>
</div>
<br>

## Features

**mail**

- list emails (list as table, json, csv + save to file)
- read emails
- send emails
- delete emails
- search emails
- move emails

**mailbox**

- list mailboxes (list as table, json, csv + save to file)

**masked**

- list aliases (list as table, json, csv + save to file)
- create aliases
- update aliases
- delete aliases
- migrate aliases (bulk export aliases in specific format for importing into external providers)
  - addy.io

## Requirements

- [uv](https://docs.astral.sh/uv/)
- Fastmail JMAP token: **Settings → Privacy & Security → Manage API tokens**

## Installation

```bash
# Clone the repository
git clone https://github.com/oregonpillow/fastmail-cli-client.git
cd fastmail-cli-client

# Install dependencies with uv
uv sync

# Or install globally
uv tool install .
```

## Configuration

Set the following environment variables:

| Variable            | Required | Default            | Description                  |
| ------------------- | -------- | ------------------ | ---------------------------- |
| `FASTMAIL_TOKEN`    | **Yes**  | —                  | Your Fastmail JMAP API token |
| `FASTMAIL_USERNAME` | No       | Auto-detected      | Your Fastmail email address  |
| `FASTMAIL_HOSTNAME` | No       | `api.fastmail.com` | JMAP server hostname         |

Generate an API token at **Settings → Privacy & Security → Manage API tokens** in the Fastmail web app.

```bash
export FASTMAIL_TOKEN="fmu1-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
export FASTMAIL_USERNAME="you@fastmail.com"
```

## Usage

Run commands using `uv run fastmail` (or just `fastmail` if installed globally):

```bash
uv run fastmail --help
```

### Account Info

```bash
# Show authenticated account info
uv run fastmail whoami
```

### Mailboxes

```bash
# List all mailboxes
uv run fastmail mailbox list
```

### Emails

```bash
# List recent inbox emails
uv run fastmail mail list --role inbox

# List emails from a specific mailbox
uv run fastmail mail list --mailbox "Drafts" --limit 5

# Read an email by ID
uv run fastmail mail read <email-id>

# Search emails
uv run fastmail mail search "meeting notes"

# Send an email
uv run fastmail mail send --to "recipient@example.com" --subject "Hello" --body "Hi there!"

# Send with body from stdin
echo "Email body here" | uv run fastmail mail send --to "recipient@example.com" --subject "Hello"

# Move an email to trash
uv run fastmail mail move <email-id> --role trash

# Move an email to a named mailbox
uv run fastmail mail move <email-id> --mailbox "Archive"

# Delete an email (with confirmation)
uv run fastmail mail delete <email-id>

# Delete without confirmation
uv run fastmail mail delete <email-id> --yes
```

### Masked Emails

Masked emails are disposable email addresses that forward to your real inbox — great for signups and privacy.

```bash
# List all masked emails
uv run fastmail masked list

# Create a new masked email
uv run fastmail masked create

# Create with options
uv run fastmail masked create \
  --domain "https://example.com" \
  --description "Shopping site" \
  --prefix "shop"

# Update a masked email
uv run fastmail masked update <masked-id> --state disabled

# Delete a masked email (sets state to 'deleted')
uv run fastmail masked delete <masked-id>
```

## References

- [Fastmail Docs: API Tokens](https://www.fastmail.help/hc/en-us/articles/5254602856719-API-tokens)
- [Fastmail API Documentation](https://www.fastmail.com/dev/)
- [Fastmail JMAP Examples](https://github.com/fastmail/JMAP-Samples)
- [addy.io CSV import template](https://app.addy.io/import-aliases-template.csv)

## Similar Projects

- [Fastmail CLI - a Rust based client](https://github.com/radiosilence/fastmail-cli)
