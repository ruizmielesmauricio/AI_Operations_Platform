import type { ReactNode } from "react";

/**
 * A deliberately tiny Markdown renderer for ORLA's help articles
 * (backend/app/support/content/*.md). It only understands what those
 * articles use — `## ` / `### ` headings, paragraphs, `- ` and `1. ` lists,
 * **bold**, `code` and [text](/in-app-path) links — and builds React
 * elements directly, so no string is ever injected as HTML. External links
 * are rendered as plain text (help content links stay in-app).
 *
 * A quoted article title such as See "Sign up and log in" becomes a link
 * to that article, so cross-references work without hand-written URLs.
 */

export function helpAnchor(heading: string): string {
  // Mirrors backend/app/support/knowledge_base.py::_anchor exactly, so
  // /help/{slug}#{anchor} deep links line up with the passage ids.
  return (heading.toLowerCase().match(/[a-z0-9]+/g) ?? []).join("-") || "section";
}

const INLINE_PATTERN = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)|"([^"]{2,80})"/g;

function renderInline(text: string, titleToSlug: Record<string, string>, keyPrefix: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let i = 0;
  INLINE_PATTERN.lastIndex = 0;
  while ((match = INLINE_PATTERN.exec(text)) !== null) {
    if (match.index > last) nodes.push(text.slice(last, match.index));
    const key = `${keyPrefix}-${i++}`;
    const [whole, bold, code, linkText, linkHref, quoted] = match;
    if (bold !== undefined) {
      nodes.push(<strong key={key}>{bold}</strong>);
    } else if (code !== undefined) {
      nodes.push(<code key={key}>{code}</code>);
    } else if (linkText !== undefined) {
      nodes.push(
        linkHref.startsWith("/") && !linkHref.startsWith("//") ? (
          <a key={key} href={linkHref}>
            {linkText}
          </a>
        ) : (
          linkText
        )
      );
    } else if (quoted !== undefined) {
      const slug = titleToSlug[quoted];
      nodes.push(
        slug ? (
          <a key={key} href={`/help/${slug}`}>
            &ldquo;{quoted}&rdquo;
          </a>
        ) : (
          whole
        )
      );
    }
    last = match.index + whole.length;
  }
  if (last < text.length) nodes.push(text.slice(last));
  return nodes;
}

type Block =
  | { kind: "h2" | "h3" | "p"; text: string }
  | { kind: "ul" | "ol"; items: string[] };

function parseBlocks(markdown: string): Block[] {
  const blocks: Block[] = [];
  let paragraph: string[] = [];
  let list: { kind: "ul" | "ol"; items: string[] } | null = null;

  const flushParagraph = () => {
    if (paragraph.length) blocks.push({ kind: "p", text: paragraph.join(" ") });
    paragraph = [];
  };
  const flushList = () => {
    if (list) blocks.push(list);
    list = null;
  };

  for (const rawLine of markdown.replace(/\r\n/g, "\n").split("\n")) {
    const line = rawLine.trimEnd();
    const unordered = /^\s*-\s+(.*)$/.exec(line);
    const ordered = /^\s*\d+\.\s+(.*)$/.exec(line);
    if (!line.trim()) {
      flushParagraph();
      flushList();
    } else if (line.startsWith("### ")) {
      flushParagraph();
      flushList();
      blocks.push({ kind: "h3", text: line.slice(4).trim() });
    } else if (line.startsWith("## ")) {
      flushParagraph();
      flushList();
      blocks.push({ kind: "h2", text: line.slice(3).trim() });
    } else if (unordered || ordered) {
      flushParagraph();
      const kind = unordered ? "ul" : "ol";
      const item = (unordered ?? ordered)![1];
      if (!list || list.kind !== kind) {
        flushList();
        list = { kind, items: [] };
      }
      list.items.push(item);
    } else if (list && /^\s{2,}\S/.test(rawLine)) {
      // Continuation of the previous list item.
      list.items[list.items.length - 1] += ` ${line.trim()}`;
    } else {
      flushList();
      paragraph.push(line.trim());
    }
  }
  flushParagraph();
  flushList();
  return blocks;
}

export function renderHelpMarkdown(markdown: string, titleToSlug: Record<string, string> = {}): ReactNode {
  return parseBlocks(markdown).map((block, index) => {
    const key = `b${index}`;
    switch (block.kind) {
      case "h2":
        return (
          <h2 key={key} id={helpAnchor(block.text)}>
            {block.text}
          </h2>
        );
      case "h3":
        return <h3 key={key}>{block.text}</h3>;
      case "p":
        return <p key={key}>{renderInline(block.text, titleToSlug, key)}</p>;
      case "ul":
        return (
          <ul key={key}>
            {block.items.map((item, j) => (
              <li key={j}>{renderInline(item, titleToSlug, `${key}-${j}`)}</li>
            ))}
          </ul>
        );
      case "ol":
        return (
          <ol key={key}>
            {block.items.map((item, j) => (
              <li key={j}>{renderInline(item, titleToSlug, `${key}-${j}`)}</li>
            ))}
          </ol>
        );
    }
  });
}
