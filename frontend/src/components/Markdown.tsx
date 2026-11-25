import type { ReactNode } from "react";

/**
 * Small, dependency-free Markdown renderer for chat replies.
 * Supports paragraphs, headings, bullet/numbered lists (with indentation),
 * fenced code blocks, simple tables, **bold**, *italic*, `inline code` and links.
 * It never injects raw HTML: everything is built as React elements, so model
 * output cannot run scripts in the page.
 */

type Block =
  | { type: "p"; text: string }
  | { type: "h"; level: number; text: string }
  | { type: "code"; text: string }
  | { type: "list"; ordered: boolean; start: number; items: { level: number; text: string; num?: number }[] }
  | { type: "table"; rows: string[][] };

const BULLET = /^(\s*)[-*+]\s+(.*)$/;
const NUMBERED = /^(\s*)(\d+)[.)]\s+(.*)$/;
const HEADING = /^(#{1,6})\s+(.*)$/;
const TABLE_ROW = /^\s*\|.*\|\s*$/;
const TABLE_SEPARATOR = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

function parseBlocks(source: string): Block[] {
  const lines = source.replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];

    if (line.trim() === "") {
      i += 1;
      continue;
    }

    if (line.trim().startsWith("```")) {
      const code: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        code.push(lines[i]);
        i += 1;
      }
      i += 1; // closing fence
      blocks.push({ type: "code", text: code.join("\n") });
      continue;
    }

    const heading = line.match(HEADING);
    if (heading) {
      blocks.push({ type: "h", level: heading[1].length, text: heading[2] });
      i += 1;
      continue;
    }

    if (TABLE_ROW.test(line)) {
      const rows: string[][] = [];
      while (i < lines.length && TABLE_ROW.test(lines[i])) {
        if (!TABLE_SEPARATOR.test(lines[i])) {
          rows.push(
            lines[i]
              .trim()
              .replace(/^\||\|$/g, "")
              .split("|")
              .map((cell) => cell.trim()),
          );
        }
        i += 1;
      }
      blocks.push({ type: "table", rows });
      continue;
    }

    const bullet = line.match(BULLET);
    const numbered = line.match(NUMBERED);
    if (bullet || numbered) {
      const ordered = !bullet && !!numbered;
      const start = numbered && !bullet ? Number(numbered[2]) : 1;
      const items: { level: number; text: string; num?: number }[] = [];
      while (i < lines.length) {
        const b = lines[i].match(BULLET);
        const n = lines[i].match(NUMBERED);
        const m = b ?? n;
        if (!m) {
          // a non-empty, indented line continues the previous item
          if (items.length && lines[i].trim() !== "" && /^\s{2,}/.test(lines[i])) {
            items[items.length - 1].text += " " + lines[i].trim();
            i += 1;
            continue;
          }
          break;
        }
        const indent = m[1].length;
        const text = b ? b[2] : (n as RegExpMatchArray)[3];
        items.push({ level: Math.min(Math.floor(indent / 2), 4), text, num: n && !b ? Number(n[2]) : undefined });
        i += 1;
      }
      blocks.push({ type: "list", ordered, start, items });
      continue;
    }

    // paragraph: consecutive lines that don't start another block
    const para: string[] = [line];
    i += 1;
    while (
      i < lines.length &&
      lines[i].trim() !== "" &&
      !HEADING.test(lines[i]) &&
      !BULLET.test(lines[i]) &&
      !NUMBERED.test(lines[i]) &&
      !TABLE_ROW.test(lines[i]) &&
      !lines[i].trim().startsWith("```")
    ) {
      para.push(lines[i]);
      i += 1;
    }
    blocks.push({ type: "p", text: para.join("\n") });
  }
  return blocks;
}

const INLINE_SOURCE =
  /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(__[^_\n]+__)|(\*[^*\s\n][^*\n]*\*)|(\[[^\]\n]+\]\((https?:\/\/[^\s)]+)\))/g;

function renderInline(text: string, keyPrefix: string): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  let n = 0;
  // a fresh regex per call: renderInline recurses (bold inside text), and a shared
  // global regex would have its lastIndex reset by the inner call
  const inline = new RegExp(INLINE_SOURCE.source, "g");
  while ((match = inline.exec(text)) !== null) {
    if (match.index > last) out.push(text.slice(last, match.index));
    const token = match[0];
    const key = `${keyPrefix}-${n++}`;
    if (match[1]) {
      out.push(<code key={key}>{token.slice(1, -1)}</code>);
    } else if (match[2] || match[3]) {
      out.push(<strong key={key}>{renderInline(token.slice(2, -2), key)}</strong>);
    } else if (match[4]) {
      out.push(<em key={key}>{renderInline(token.slice(1, -1), key)}</em>);
    } else if (match[5]) {
      const label = token.slice(1, token.indexOf("]("));
      out.push(
        <a key={key} href={match[6]} target="_blank" rel="noopener noreferrer">
          {label}
        </a>,
      );
    }
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

export function Markdown({ text }: { text: string }) {
  const blocks = parseBlocks(text);
  return (
    <>
      {blocks.map((block, bi) => {
        const key = `b${bi}`;
        switch (block.type) {
          case "h":
            return (
              <p key={key} className={`md-h md-h${Math.min(block.level, 3)}`}>
                {renderInline(block.text, key)}
              </p>
            );
          case "code":
            return (
              <pre key={key} className="md-pre">
                <code>{block.text}</code>
              </pre>
            );
          case "table":
            return (
              <div key={key} className="md-table-wrap">
                <table className="md-table">
                  <tbody>
                    {block.rows.map((row, ri) => (
                      <tr key={ri}>
                        {row.map((cell, ci) =>
                          ri === 0 ? (
                            <th key={ci}>{renderInline(cell, `${key}-${ri}-${ci}`)}</th>
                          ) : (
                            <td key={ci}>{renderInline(cell, `${key}-${ri}-${ci}`)}</td>
                          ),
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "list": {
            const items = block.items.map((item, ii) => (
              <li
                key={ii}
                className={`md-li md-l${item.level}`}
                value={block.ordered && item.level === 0 ? item.num : undefined}
              >
                {renderInline(item.text, `${key}-${ii}`)}
              </li>
            ));
            return block.ordered ? (
              <ol key={key} className="md-list" start={block.start}>
                {items}
              </ol>
            ) : (
              <ul key={key} className="md-list">
                {items}
              </ul>
            );
          }
          default:
            return (
              <p key={key} className="md-p">
                {renderInline(block.text, key)}
              </p>
            );
        }
      })}
    </>
  );
}
