/*
 * Markdown rendering: escapeHtml, inline markdown, tables, full markdown.
 * Also includes createVoiceMessagePlayerHtml (used in inline markdown rendering).
 */

import { createVoiceMessagePlayerHtml } from "./voice-player.js";

export function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderInlineMarkdown(text) {
  let output = text;
  // Replace TTS audio URLs with voice message player (before other link processing)
  output = output.replace(/(?:\[([^\]]*)\]\()?\/api\/tts\/audio\/[a-f0-9\-]+\.mp3\)?/gi, function (match, linkText) {
    var urlMatch = match.match(/\/api\/tts\/audio\/[a-f0-9\-]+\.mp3/i);
    if (urlMatch) return createVoiceMessagePlayerHtml(urlMatch[0]);
    return match;
  });
  output = output.replace(/~~([^~]+)~~/g, "<del>$1</del>");
  output = output.replace(/\*\*\*([^*]+)\*\*\*/g, "<strong><em>$1</em></strong>");
  output = output.replace(/`([^`]+)`/g, "<code>$1</code>");
  output = output.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  output = output.replace(/\*([^*]+)\*/g, "<em>$1</em>");
  output = output.replace(/!\[([^\]]*)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer"><img src="$2" alt="$1" referrerpolicy="no-referrer" loading="lazy" onerror="handleInlineImageError(this)" /></a>');
  output = output.replace(/\[([^\]]+)\]\((\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" download>$1</a>');
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer" download>$1</a>');
  output = output.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  output = output.replace(/(^|[^"=])(https?:\/\/[^\s<>]+\.(?:png|jpe?g|gif|webp|svg|bmp|ico)(?:\?[^\s<>]*)?)(?=$|[\s,;)\]&])/gi, '$1<a href="$2" target="_blank" rel="noopener noreferrer"><img src="$2" alt="$2" referrerpolicy="no-referrer" loading="lazy" onerror="handleInlineImageError(this)" /></a>');
  output = output.replace(/(^|[\s(])(\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})(?=$|[\s,;)\]])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer" download>$2</a>');
  output = output.replace(/(^|[\s(])(https?:\/\/[^\s)\]]+\/api\/files\/shared\/[A-Za-z0-9_-]{10,200})(?=$|[\s,;)\]])/g, '$1<a href="$2" target="_blank" rel="noopener noreferrer" download>$2</a>');
  return output;
}

function isTableSeparatorRow(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  if (!normalized) {
    return false;
  }

  const parts = normalized.split("|").map((part) => part.trim());
  if (parts.length === 0) {
    return false;
  }

  return parts.every((part) => /^:?-{3,}:?$/.test(part));
}

function parseTableCells(line) {
  const normalized = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return normalized.split("|").map((cell) => renderInlineMarkdown(cell.trim()));
}

export function renderMarkdown(rawText) {
  const escaped = escapeHtml(rawText || "");
  const lines = escaped.split("\n");
  const html = [];
  let inCodeBlock = false;
  let inUlList = false;
  let inOlList = false;

  function closeOpenLists() {
    if (inUlList) {
      html.push("</ul>");
      inUlList = false;
    }

    if (inOlList) {
      html.push("</ol>");
      inOlList = false;
    }
  }

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      if (!inCodeBlock) {
        closeOpenLists();
        html.push("<pre><code>");
        inCodeBlock = true;
      } else {
        html.push("</code></pre>");
        inCodeBlock = false;
      }
      continue;
    }

    if (inCodeBlock) {
      html.push(`${line}\n`);
      continue;
    }

    if (trimmed.includes("|") && i + 1 < lines.length && isTableSeparatorRow(lines[i + 1])) {
      closeOpenLists();

      const headerCells = parseTableCells(trimmed);
      html.push("<table><thead><tr>");
      headerCells.forEach((cell) => {
        html.push(`<th>${cell}</th>`);
      });
      html.push("</tr></thead><tbody>");

      i += 2;
      while (i < lines.length) {
        const rowLine = lines[i];
        if (!rowLine.trim() || !rowLine.includes("|")) {
          i -= 1;
          break;
        }

        const rowCells = parseTableCells(rowLine);
        html.push("<tr>");
        rowCells.forEach((cell) => {
          html.push(`<td>${cell}</td>`);
        });
        html.push("</tr>");
        i += 1;
      }

      html.push("</tbody></table>");
      continue;
    }

    const unorderedMatch = trimmed.match(/^[-*+]\s+(.*)$/);
    if (unorderedMatch) {
      if (!inUlList) {
        if (inOlList) {
          html.push("</ol>");
          inOlList = false;
        }
        html.push("<ul>");
        inUlList = true;
      }
      html.push(`<li>${renderInlineMarkdown(unorderedMatch[1])}</li>`);
      continue;
    }

    const orderedMatch = trimmed.match(/^\d+\.\s+(.*)$/);
    if (orderedMatch) {
      if (!inOlList) {
        if (inUlList) {
          html.push("</ul>");
          inUlList = false;
        }
        html.push("<ol>");
        inOlList = true;
      }
      html.push(`<li>${renderInlineMarkdown(orderedMatch[1])}</li>`);
      continue;
    }

    closeOpenLists();

    if (/^---+$/.test(trimmed) || /^\*\*\*+$/.test(trimmed)) {
      html.push("<hr>");
      continue;
    }

    if (trimmed.startsWith("> ")) {
      html.push(`<blockquote>${renderInlineMarkdown(trimmed.slice(2))}</blockquote>`);
      continue;
    }

    if (trimmed.length === 0) {
      html.push("<br>");
      continue;
    }

    const headingMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      const level = headingMatch[1].length;
      html.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }

    html.push(`<p>${renderInlineMarkdown(trimmed)}</p>`);
  }

  closeOpenLists();

  if (inCodeBlock) {
    html.push("</code></pre>");
  }

  return html.join("");
}

export function handleInlineImageError(img) {
  const url = img.src;
  const alt = img.alt || url;
  const link = document.createElement("a");
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.textContent = alt;
  const wrapper = img.parentElement;
  if (wrapper && wrapper.tagName === "A") {
    wrapper.replaceWith(link);
  } else {
    img.replaceWith(link);
  }
}

/* Expose to window for onerror= in dynamically generated img tags. */
window.handleInlineImageError = handleInlineImageError;
