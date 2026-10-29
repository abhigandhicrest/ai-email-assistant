# Gmail setup

n8n reads mail from a dedicated Gmail test account. The workflow does not send mail, mark messages read, or download attachments.

n8n 2.35.7 is installed. A Google OAuth client is not configured yet. Create that in Google Cloud and n8n, outside this repository. Do not put the client secret, refresh token, or Gmail password in this project.

## Google Cloud

1. Open [Google Cloud Console](https://console.cloud.google.com/) and create or select a project.
2. Enable the Gmail API for that project.
3. Configure the OAuth consent screen. For a local test, choose External, keep the app in Testing, and add the test Gmail address as a test user.
4. Create an OAuth client ID of type Web application.
5. Copy the OAuth redirect URL from the n8n credential screen. For n8n on this computer it is usually `http://localhost:5678/rest/oauth2-credential/callback`. Paste that exact value into Authorized redirect URIs.
6. Copy the client ID and client secret into the n8n credential only.

## n8n credential

Create a Gmail OAuth2 credential:

1. Turn on Custom Scopes. Current self-hosted n8n (the July 2026 credential update or newer) has this toggle. An older n8n build requests broader Gmail scopes and should not be used for this workflow.
2. Replace the scope list with only:

```text
https://www.googleapis.com/auth/gmail.readonly
```

3. Do not include `gmail.compose`, `gmail.modify`, `gmail.send`, or `https://mail.google.com/`.
4. Select Sign in with Google and choose the test account.
5. Save the credential in n8n. Leave it out of the exported workflow.

`gmail.readonly` is enough to list and read messages. The API still refuses a second copy of the same Gmail message id, so the workflow does not need permission to change labels.

## What stays out of source control

- OAuth client secret
- Refresh token and access token
- The test account password
- The application `API_KEY`

The file `n8n/workflows/ai_email_assistant.json` has no credential block. After import, select the Gmail credential on the Gmail Trigger node.
