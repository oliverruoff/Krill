import http from "node:http";
import process from "node:process";
import whatsapp from "whatsapp-web.js";
import qrcode from "qrcode";

const { Client, LocalAuth } = whatsapp;

const port = Number.parseInt(process.env.WA_SIDECAR_PORT || "18777", 10);

let client = null;
let status = "disconnected";
let qrDataUrl = "";
let events = [];
let allowlist = new Set();
let initStarted = false;

function json(res, code, payload) {
  res.writeHead(code, { "Content-Type": "application/json" });
  res.end(JSON.stringify(payload));
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      if (!chunks.length) {
        resolve({});
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(chunks).toString("utf-8")));
      } catch (err) {
        reject(err);
      }
    });
    req.on("error", reject);
  });
}

function normalizeNumber(raw) {
  const cleaned = String(raw || "").replace(/[^0-9+]/g, "").trim();
  if (!cleaned) return "";
  let normalized = cleaned.startsWith("+") ? cleaned.slice(1) : cleaned;
  if (normalized.startsWith("00")) {
    normalized = normalized.slice(2);
  }
  return normalized.replace(/[^0-9]/g, "");
}

function toChatId(number) {
  const normalized = normalizeNumber(number);
  if (!normalized) {
    throw new Error("Invalid phone number.");
  }
  return `${normalized}@c.us`;
}

function inferHasImage(message) {
  const messageType = String(message?.type || "").toLowerCase();
  return Boolean(message?.hasMedia) && messageType === "image";
}

function normalizeMessageText(message) {
  return String(message?.body || "").trim();
}

async function getImageMediaForMessage(message) {
  if (!inferHasImage(message)) {
    return { ok: false, detail: "Message has no image media." };
  }
  if (!message || typeof message.downloadMedia !== "function") {
    return { ok: false, detail: "Message media is unavailable." };
  }

  let media = null;
  try {
    media = await message.downloadMedia();
  } catch {
    return { ok: false, detail: "Failed to download message media." };
  }

  const mimeType = String(media?.mimetype || "").trim().toLowerCase();
  const contentBase64 = String(media?.data || "").trim();
  if (!mimeType.startsWith("image/") || !contentBase64) {
    return { ok: false, detail: "Message media is not an image." };
  }

  const sizeBytes = Math.floor((contentBase64.length * 3) / 4);
  if (sizeBytes <= 0) {
    return { ok: false, detail: "Image payload is empty." };
  }
  if (sizeBytes > 10 * 1024 * 1024) {
    return { ok: false, detail: "Image exceeds 10MB limit." };
  }

  return {
    ok: true,
    mime_type: mimeType,
    content_base64: contentBase64,
    size_bytes: sizeBytes,
  };
}

async function getRecentMessages(chat, limit) {
  const fetchLimit = Number.isFinite(limit) ? Math.max(1, Math.min(30, Math.floor(limit))) : 10;
  const messages = await chat.fetchMessages({ limit: fetchLimit });
  return messages
    .filter((message) => {
      const type = String(message?.type || "").toLowerCase();
      return type === "chat" || type === "image";
    })
    .map((message) => ({
      id: String(message?.id?._serialized || ""),
      body: normalizeMessageText(message),
      from_me: Boolean(message?.fromMe),
      timestamp: Number.isFinite(Number(message?.timestamp)) ? Number(message.timestamp) : 0,
      has_image: inferHasImage(message),
      type: String(message?.type || "").toLowerCase(),
    }));
}

async function getMessageById(chat, messageId, limit = 50) {
  const messages = await chat.fetchMessages({ limit });
  for (const message of messages) {
    const currentId = String(message?.id?._serialized || "");
    if (currentId && currentId === messageId) {
      return message;
    }
  }
  return null;
}

async function listContacts() {
  await ensureClient();
  if (!client || (status !== "ready" && status !== "authenticated")) {
    return [];
  }
  let contacts = [];
  try {
    contacts = await client.getContacts();
  } catch {
    return [];
  }
  const result = [];
  for (const contact of contacts) {
    const serialized = String(contact?.id?._serialized || "").trim();
    if (!serialized.endsWith("@c.us")) {
      continue;
    }
    const number = normalizeNumber(serialized.replace("@c.us", ""));
    if (!number) {
      continue;
    }
    const displayName = String(contact.pushname || contact.name || contact.shortName || number).trim() || number;
    result.push({ number, name: displayName });
  }
  result.sort((a, b) => a.name.localeCompare(b.name));
  return result;
}

async function ensureClient() {
  if (client) {
    if (!initStarted) {
      initStarted = true;
      status = "initializing";
      client.initialize().catch(() => {
        status = "error";
      });
    }
    return;
  }
  client = new Client({
    authStrategy: new LocalAuth({ dataPath: authDir, clientId: "krill" }),
    puppeteer: {
      headless: true,
      executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
      args: ["--no-sandbox", "--disable-setuid-sandbox"],
    },
  });

  client.on("qr", async (qr) => {
    status = "qr";
    try {
      qrDataUrl = await qrcode.toDataURL(qr);
    } catch {
      qrDataUrl = "";
    }
  });
  client.on("ready", () => {
    status = "ready";
    qrDataUrl = "";
  });
  client.on("authenticated", () => {
    status = "authenticated";
  });
  client.on("auth_failure", () => {
    status = "auth_failure";
  });
  client.on("disconnected", () => {
    status = "disconnected";
  });
  client.on("message", (msg) => {
    if (msg.fromMe) {
      return;
    }
    const from = String(msg.from || "").trim();
    if (!from.endsWith("@c.us")) {
      return;
    }
    const number = normalizeNumber(from.replace("@c.us", ""));
    const text = normalizeMessageText(msg);
    const hasImage = inferHasImage(msg);
    if (!text && !hasImage) {
      return;
    }
    if (allowlist.size > 0 && !allowlist.has(number)) {
      return;
    }
    events.push({
      id: String(msg.id?._serialized || ""),
      from_number: number,
      text,
      has_image: hasImage,
      timestamp_ms: Date.now(),
    });
    if (events.length > 300) {
      events = events.slice(events.length - 300);
    }
  });

  status = "initializing";
  initStarted = true;
  client.initialize().catch(() => {
    status = "error";
  });
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url || "/", `http://127.0.0.1:${port}`);
    if (req.method === "GET" && url.pathname === "/health") {
      json(res, 200, { ok: true, status });
      return;
    }

    if (req.method === "POST" && url.pathname === "/connect") {
      await ensureClient();
      json(res, 200, { ok: true, status });
      return;
    }

    if (req.method === "GET" && url.pathname === "/status") {
      json(res, 200, { ok: true, status, qr_data_url: qrDataUrl });
      return;
    }

    if (req.method === "POST" && url.pathname === "/send") {
      await ensureClient();
      if (status !== "ready") {
        json(res, 422, { ok: false, detail: "WhatsApp is not ready. Connect first and scan QR." });
        return;
      }
      const body = await readJsonBody(req);
      const to = String(body.to_number || "");
      const text = String(body.text || "").trim();
      if (!text) {
        json(res, 422, { ok: false, detail: "text is required" });
        return;
      }
      const chatId = toChatId(to);
      await client.sendMessage(chatId, text);
      json(res, 200, { ok: true, to_number: normalizeNumber(to), text });
      return;
    }

    if (req.method === "POST" && url.pathname === "/messages/history") {
      await ensureClient();
      if (status !== "ready") {
        json(res, 422, { ok: false, detail: "WhatsApp is not ready." });
        return;
      }
      const body = await readJsonBody(req);
      const number = String(body.number || "");
      const limit = Number.parseInt(body.limit || "10", 10);
      if (!number) {
        json(res, 422, { ok: false, detail: "number is required" });
        return;
      }
      const chatId = toChatId(number);
      const chat = await client.getChatById(chatId);
      const history = await getRecentMessages(chat, limit);
      json(res, 200, { ok: true, history });
      return;
    }

    if (req.method === "POST" && url.pathname === "/messages/media") {
      await ensureClient();
      if (status !== "ready") {
        json(res, 422, { ok: false, detail: "WhatsApp is not ready." });
        return;
      }

      const body = await readJsonBody(req);
      const number = String(body.number || "").trim();
      const messageId = String(body.message_id || "").trim();
      if (!number || !messageId) {
        json(res, 422, { ok: false, detail: "number and message_id are required" });
        return;
      }

      const chatId = toChatId(number);
      const chat = await client.getChatById(chatId);
      const message = await getMessageById(chat, messageId, 50);
      if (!message) {
        json(res, 404, { ok: false, detail: "Message not found in recent history." });
        return;
      }

      const media = await getImageMediaForMessage(message);
      if (!media.ok) {
        json(res, 422, { ok: false, detail: media.detail });
        return;
      }

      json(res, 200, {
        ok: true,
        number: normalizeNumber(number),
        message_id: messageId,
        mime_type: media.mime_type,
        content_base64: media.content_base64,
        size_bytes: media.size_bytes,
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/allowlist") {

      const body = await readJsonBody(req);
      const numbers = Array.isArray(body.numbers) ? body.numbers : [];
      const next = new Set();
      for (const raw of numbers) {
        const normalized = normalizeNumber(raw);
        if (normalized) {
          next.add(normalized);
        }
      }
      allowlist = next;
      json(res, 200, { ok: true, count: allowlist.size });
      return;
    }

    if (req.method === "GET" && url.pathname === "/contacts") {
      const contacts = await listContacts();
      json(res, 200, { ok: true, contacts });
      return;
    }

    if (req.method === "GET" && url.pathname === "/events/poll") {
      const take = events;
      events = [];
      json(res, 200, { ok: true, events: take });
      return;
    }

    if (req.method === "POST" && url.pathname === "/shutdown") {
      try {
        if (client) {
          await client.destroy();
        }
      } catch {
        // Best-effort cleanup before shutdown.
      }
      client = null;
      status = "disconnected";
      qrDataUrl = "";
      json(res, 200, { ok: true });
      server.close(() => process.exit(0));
      return;
    }

    json(res, 404, { ok: false, detail: "Not found" });
  } catch (err) {
    json(res, 500, { ok: false, detail: String(err && err.message ? err.message : err) });
  }
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`whatsapp-sidecar listening on ${port}\n`);
});
const authDir = process.env.WA_AUTH_DIR || "/tmp/krill_wa_auth";
