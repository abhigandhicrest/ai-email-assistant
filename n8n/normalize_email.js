// Normalize one Gmail message into the Python API payload.
// This file is copied into n8n/workflows/ai_email_assistant.json.
// Keep credentials out of this file.

const MAX_IDENTIFIER = 255;
const MAX_SUBJECT = 500;
const MAX_BODY = 20000;
const EMAIL_ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}/;

function normalizeGmailMessage(message) {
  if (message === null || typeof message !== "object" || Array.isArray(message)) {
    return skipped("unsupported format", null);
  }

  const emailIdentifier = cleanIdentifier(message.id);
  if (!emailIdentifier) {
    return skipped("missing email identifier", null);
  }

  const labels = labelsOf(message);
  if (labels.includes("DRAFT")) {
    return skipped("draft", emailIdentifier);
  }
  if (labels.includes("SENT") && !labels.includes("INBOX")) {
    return skipped("sent mail", emailIdentifier);
  }

  const sender = extractSender(message);
  if (!sender) {
    return skipped("missing sender", emailIdentifier);
  }

  const receivedAt = extractReceivedAt(message);
  if (!receivedAt) {
    return skipped("missing received timestamp", emailIdentifier);
  }

  const body = extractBody(message);
  if (!body) {
    if (snippetOnly(message)) {
      return skipped("message body was not included", emailIdentifier);
    }
    return skipped(
      isNonText(message) ? "unsupported format" : "empty message",
      emailIdentifier,
    );
  }

  return {
    ok: true,
    email_identifier: emailIdentifier,
    payload: {
      email_identifier: emailIdentifier,
      sender_address: sender,
      subject: extractSubject(message),
      body_text: body,
      received_at: receivedAt,
    },
  };
}

function skipped(reason, emailIdentifier) {
  return { ok: false, reason, email_identifier: emailIdentifier };
}

function cleanIdentifier(value) {
  if (value === null || value === undefined) {
    return null;
  }
  const identifier = String(value).trim();
  if (
    !identifier ||
    identifier.length > MAX_IDENTIFIER ||
    /[\u0000-\u001F\u007F\s]/.test(identifier)
  ) {
    return null;
  }
  return identifier;
}

function labelsOf(message) {
  if (Array.isArray(message.labelIds)) {
    return message.labelIds.map((label) => String(label));
  }
  if (Array.isArray(message.labels)) {
    return message.labels.map((label) => String(label.name || label.id || label));
  }
  return [];
}

function extractSender(message) {
  const candidates = [
    message.from,
    message.From,
    headerValue(message, "from"),
  ];
  for (const candidate of candidates) {
    const address = firstAddress(candidate);
    if (address) {
      return address;
    }
  }
  return null;
}

function firstAddress(value) {
  if (!value) {
    return null;
  }
  if (typeof value === "string") {
    const match = value.match(EMAIL_ADDRESS);
    return match ? match[0] : null;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const address = firstAddress(item && (item.address || item.text || item));
      if (address) {
        return address;
      }
    }
    return null;
  }
  if (typeof value === "object") {
    return (
      firstAddress(value.value) ||
      firstAddress(value.text) ||
      firstAddress(value.address)
    );
  }
  return null;
}

function headerValue(message, name) {
  const headers = message.headers;
  if (headers && typeof headers === "object" && !Array.isArray(headers)) {
    for (const [key, value] of Object.entries(headers)) {
      if (key.toLowerCase() === name) {
        return value;
      }
    }
  }
  const payloadHeaders = message.payload && message.payload.headers;
  if (Array.isArray(payloadHeaders)) {
    const found = payloadHeaders.find(
      (header) => String(header.name || "").toLowerCase() === name,
    );
    if (found) {
      return found.value;
    }
  }
  return null;
}

function extractReceivedAt(message) {
  return (
    parseTimestamp(message.date) ||
    parseTimestamp(message.internalDate) ||
    parseTimestamp(headerValue(message, "date"))
  );
}

function parseTimestamp(value) {
  if (value === null || value === undefined || value === false || value === "") {
    return null;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    const milliseconds = value < 1e12 ? value * 1000 : value;
    return isoOrNull(new Date(milliseconds));
  }
  const text = String(value).trim().replace(/^date:\s*/i, "");
  if (!text) {
    return null;
  }
  if (/^\d{11,}$/.test(text)) {
    return parseTimestamp(Number(text));
  }
  return isoOrNull(new Date(text));
}

function isoOrNull(date) {
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function extractSubject(message) {
  const raw = message.subject || message.Subject || headerValue(message, "subject");
  if (raw === null || raw === undefined || raw === false) {
    return null;
  }
  const cleaned = collapse(stripControls(String(raw))).replace(/\n+/g, " ");
  if (!cleaned) {
    return null;
  }
  return cleaned.length <= MAX_SUBJECT ? cleaned : cleaned.slice(0, MAX_SUBJECT);
}

function extractBody(message) {
  const plain = typeof message.text === "string" ? collapse(stripControls(message.text)) : "";
  if (plain) {
    return limitText(plain, MAX_BODY);
  }
  if (typeof message.html === "string" && message.html.trim()) {
    const fromHtml = stripHtml(message.html);
    if (fromHtml) {
      return limitText(fromHtml, MAX_BODY);
    }
  }

  const parts = [];
  collectParts(message.payload, parts);
  const plainPart = parts.find((part) => part.mime === "text/plain");
  const htmlPart = parts.find((part) => part.mime === "text/html");
  if (plainPart) {
    const text = collapse(stripControls(plainPart.text));
    if (text) {
      return limitText(text, MAX_BODY);
    }
  }
  if (htmlPart) {
    const text = stripHtml(htmlPart.text);
    if (text) {
      return limitText(text, MAX_BODY);
    }
  }
  return null;
}

function snippetOnly(message) {
  if (typeof message.snippet !== "string" || !message.snippet.trim()) {
    return false;
  }
  if (message.text || message.html) {
    return false;
  }
  if (!message.payload) {
    return true;
  }
  const parts = [];
  collectParts(message.payload, parts);
  const data = message.payload.body && message.payload.body.data;
  return parts.length === 0 && !data;
}

function isNonText(message) {
  if (!message.payload) {
    return false;
  }
  const mimes = [];
  collectMimes(message.payload, mimes);
  if (mimes.length === 0) {
    return nonTextMime(message.payload.mimeType);
  }
  return mimes.every((mime) => !mime.startsWith("text/") && !mime.startsWith("multipart/"));
}

function nonTextMime(mime) {
  const value = String(mime || "").toLowerCase();
  return (
    value.startsWith("application/") ||
    value.startsWith("image/") ||
    value.startsWith("audio/") ||
    value.startsWith("video/")
  );
}

function collectParts(part, found) {
  if (!part || typeof part !== "object") {
    return;
  }
  const mime = String(part.mimeType || "").toLowerCase();
  const data = part.body && part.body.data;
  if (data && (mime === "text/plain" || mime === "text/html")) {
    found.push({ mime, text: decodeBase64Url(data) });
  }
  for (const child of part.parts || []) {
    collectParts(child, found);
  }
}

function collectMimes(part, found) {
  if (!part || typeof part !== "object") {
    return;
  }
  if (part.mimeType) {
    found.push(String(part.mimeType).toLowerCase());
  }
  for (const child of part.parts || []) {
    collectMimes(child, found);
  }
}

function decodeBase64Url(value) {
  try {
    return Buffer.from(String(value), "base64url").toString("utf8");
  } catch (_error) {
    return "";
  }
}

function stripHtml(value) {
  let text = String(value);
  text = text.replace(/<script[\s\S]*?<\/script>/gi, " ");
  text = text.replace(/<style[\s\S]*?<\/style>/gi, " ");
  text = text.replace(/<(?:br|\/p|\/div|\/tr|\/li|\/h[1-6])\b[^>]*>/gi, "\n");
  text = text.replace(/<[^>]+>/g, " ");
  text = decodeEntities(text);
  text = text.replace(/<[^>]+>/g, " ");
  return collapse(stripControls(text));
}

function decodeEntities(value) {
  return value
    .replace(/&#(\d+);/g, (_match, digits) => safeCharacter(Number(digits)))
    .replace(/&#x([0-9a-f]+);/gi, (_match, hex) => safeCharacter(parseInt(hex, 16)))
    .replace(/&nbsp;/gi, " ")
    .replace(/&quot;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/&lt;/gi, "<")
    .replace(/&gt;/gi, ">")
    .replace(/&amp;/gi, "&");
}

function safeCharacter(codePoint) {
  if (!Number.isFinite(codePoint) || codePoint < 32 || codePoint === 127) {
    return " ";
  }
  try {
    return String.fromCodePoint(codePoint);
  } catch (_error) {
    return " ";
  }
}

function stripControls(value) {
  return String(value).replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "");
}

function collapse(value) {
  return String(value)
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function limitText(value, limit) {
  if (value.length <= limit) {
    return value;
  }
  const suffix = "\n[truncated]";
  return value.slice(0, limit - suffix.length).trimEnd() + suffix;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { normalizeGmailMessage };
}
