/**
 * Open WebUI ↔ MCP Apps host bridge — `static/loader.js`.
 *
 * Open WebUI loads `/static/loader.js` into its main window on every page
 * (see app.html). This runs an {@link AppBridge} *in the parent window*, which
 * is the only place the `ui/initialize` handshake can be answered: an App
 * inside a sandboxed iframe posts `ui/initialize` to `window.parent`, and only
 * the parent (which owns the iframe) can respond and proxy `tools/call`.
 *
 * The companion `tool.py` injects a marker comment carrying the tool result and
 * MCP server URL into the iframe's `srcdoc`. We read that attribute from the
 * parent, attach an AppBridge per matching iframe, and forward server-tool
 * calls to the MCP server over streamable HTTP.
 */
import { PostMessageTransport } from "@modelcontextprotocol/ext-apps";
import { AppBridge } from "@modelcontextprotocol/ext-apps/app-bridge";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";
import { CallToolResultSchema } from "@modelcontextprotocol/sdk/types.js";
import { z } from "zod";

// Open WebUI's page CSP may forbid `unsafe-eval`; force zod's interpreter path.
try {
  (z as unknown as { config?: (o: { jitless: boolean }) => void }).config?.({
    jitless: true,
  });
} catch {
  /* older zod: no-op */
}

const MARKER = /<!--__MCP_APP_BRIDGE__ ([A-Za-z0-9+/=]+) -->/;

interface BridgeConfig {
  serverUrl?: string;
  toolName?: string;
  args?: Record<string, unknown>;
  resultText?: string;
  structuredContent?: Record<string, unknown>;
  maxHeight?: number;
}

const attached = new WeakSet<HTMLIFrameElement>();
const clients = new Map<string, Promise<Client>>();

function decodeConfig(srcdoc: string | null): BridgeConfig | null {
  if (!srcdoc) return null;
  const m = srcdoc.match(MARKER);
  if (!m) return null;
  try {
    const bytes = Uint8Array.from(atob(m[1]), (c) => c.charCodeAt(0));
    return JSON.parse(new TextDecoder().decode(bytes)) as BridgeConfig;
  } catch {
    return null;
  }
}

function getClient(url: string): Promise<Client> {
  let p = clients.get(url);
  if (!p) {
    p = (async () => {
      const client = new Client({ name: "open-webui-loader", version: "0.1.0" });
      await client.connect(new StreamableHTTPClientTransport(new URL(url)));
      return client;
    })();
    clients.set(url, p);
  }
  return p;
}

function detectTheme(): "light" | "dark" {
  return document.documentElement.classList.contains("dark") ? "dark" : "light";
}

/** Extract plain text from an MCP-UI message's content blocks. */
function messageText(content: unknown): string {
  if (!Array.isArray(content)) return "";
  return content
    .filter(
      (b): b is { type: "text"; text: string } =>
        !!b &&
        typeof b === "object" &&
        (b as { type?: unknown }).type === "text" &&
        typeof (b as { text?: unknown }).text === "string",
    )
    .map((b) => b.text)
    .join("\n")
    .trim();
}

/**
 * Inject text into Open WebUI's chat composer and submit it, so an app's
 * `app.sendMessage(...)` appears as a real user turn. `#chat-input` is the
 * ProseMirror contenteditable (the id is applied via editorProps.attributes);
 * `execCommand("insertText")` fires the beforeinput event ProseMirror needs to
 * update its document + the Svelte binding the send button reads.
 */
function deliverMessageToChat(text: string): boolean {
  const input = document.getElementById("chat-input");
  if (!input || !text) return false;
  input.focus();
  const ok = document.execCommand("insertText", false, text);
  if (!ok) {
    // Fallback for engines that ignore execCommand on contenteditable.
    input.dispatchEvent(
      new InputEvent("beforeinput", {
        inputType: "insertText",
        data: text,
        bubbles: true,
        cancelable: true,
      }),
    );
  }
  // Let ProseMirror's onUpdate propagate to the bound prompt (which gates the
  // send button's disabled state) before clicking it.
  setTimeout(() => {
    const send = document.getElementById("send-message-button");
    if (send instanceof HTMLButtonElement && !send.disabled) {
      send.click();
    } else {
      input.dispatchEvent(
        new KeyboardEvent("keydown", {
          key: "Enter",
          code: "Enter",
          bubbles: true,
          cancelable: true,
        }),
      );
    }
  }, 50);
  return true;
}

async function attachBridge(iframe: HTMLIFrameElement, cfg: BridgeConfig) {
  if (attached.has(iframe) || !iframe.contentWindow) return;
  attached.add(iframe);

  const bridge = new AppBridge(
    null,
    { name: "Open WebUI", version: "0.1.0" },
    {
      openLinks: {},
      serverTools: {},
      updateModelContext: { text: {} },
      message: { text: {} },
      logging: {},
    },
    {
      hostContext: {
        theme: detectTheme(),
        platform: "web",
        displayMode: "inline",
        availableDisplayModes: ["inline"],
        containerDimensions: {
          width: iframe.clientWidth || 800,
          maxHeight: cfg.maxHeight || 6000,
        },
      },
    },
  );

  // Deliver the tool input + result the LLM already triggered, via the real
  // protocol (so app.ontoolinput / app.ontoolresult fire after the handshake).
  bridge.addEventListener("initialized", () => {
    void bridge.sendToolInput({ arguments: cfg.args ?? {} });
    void bridge.sendToolResult({
      content: [{ type: "text", text: cfg.resultText ?? "" }],
      ...(cfg.structuredContent
        ? { structuredContent: cfg.structuredContent }
        : {}),
    });
  });

  bridge.onopenlink = async ({ url }) => {
    window.open(url, "_blank", "noopener,noreferrer");
    return {};
  };
  bridge.onmessage = async (params) => {
    const text = messageText((params as { content?: unknown }).content);
    const delivered = deliverMessageToChat(text);
    if (!delivered) {
      console.warn(
        "[mcp-app-bridge] could not deliver message to chat (no #chat-input or empty text):",
        params,
      );
    }
    return {};
  };
  bridge.onupdatemodelcontext = async () => ({});
  bridge.onloggingmessage = (p) => console.info("[mcp-app-bridge] log:", p);
  bridge.onsizechange = async ({ height }) => {
    if (typeof height === "number") iframe.style.height = `${height}px`;
  };

  // Live server-tool calls (e.g. a "Get Server Time" button): forward to the
  // MCP server. Requires CORS on the server; authenticated servers need a proxy.
  if (cfg.serverUrl) {
    bridge.oncalltool = async (params, extra) => {
      const client = await getClient(cfg.serverUrl!);
      return client.request(
        { method: "tools/call", params },
        CallToolResultSchema,
        { signal: extra.signal },
      );
    };
  }

  await bridge.connect(
    new PostMessageTransport(iframe.contentWindow, iframe.contentWindow),
  );
}

function tryAttach(iframe: HTMLIFrameElement) {
  const cfg = decodeConfig(iframe.getAttribute("srcdoc"));
  if (cfg) void attachBridge(iframe, cfg);
}

function scan(root: ParentNode | HTMLElement) {
  if (root instanceof HTMLIFrameElement) tryAttach(root);
  root.querySelectorAll?.("iframe").forEach((el) =>
    tryAttach(el as HTMLIFrameElement),
  );
}

// Attach as soon as a matching iframe element is inserted (or its srcdoc is
// set) — before the App inside loads and posts ui/initialize.
const observer = new MutationObserver((mutations) => {
  for (const m of mutations) {
    if (m.type === "attributes" && m.target instanceof HTMLIFrameElement) {
      tryAttach(m.target);
    }
    m.addedNodes.forEach((n) => {
      if (n instanceof HTMLElement) scan(n);
    });
  }
});

observer.observe(document.documentElement, {
  childList: true,
  subtree: true,
  attributes: true,
  attributeFilter: ["srcdoc"],
});

scan(document);

console.log("??????????");