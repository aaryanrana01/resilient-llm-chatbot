import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render } from "@testing-library/react";
import { Markdown } from "./Markdown";

afterEach(() => cleanup());

describe("Markdown", () => {
  it("renders bold, code, lists and nested bullets without raw symbols", () => {
    const text = [
      "REST APIs use HTTP. Key points:",
      "",
      "- **Resources** are URLs (e.g., `/users/123`).",
      "- **HTTP verbs**:",
      "  - GET – retrieve",
      "  - POST – create",
      "",
      "1. First",
      "2. Second",
    ].join("\n");
    const { container } = render(<Markdown text={text} />);
    expect(container.textContent).not.toContain("**");
    expect(container.textContent).not.toContain("`");
    expect(container.querySelectorAll("strong")).toHaveLength(2);
    expect(container.querySelector("code")?.textContent).toBe("/users/123");
    expect(container.querySelectorAll("ul li")).toHaveLength(4);
    expect(container.querySelectorAll("ol li")).toHaveLength(2);
  });

  it("never renders raw HTML from the model", () => {
    const { container } = render(<Markdown text={'<img src=x onerror="alert(1)"> hi'} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img");
  });

  it("renders code fences and tables", () => {
    const { container } = render(<Markdown text={"```\nprint(1)\n```\n\n| a | b |\n|---|---|\n| 1 | 2 |"} />);
    expect(container.querySelector("pre")?.textContent).toBe("print(1)");
    expect(container.querySelectorAll("th")).toHaveLength(2);
    expect(container.querySelectorAll("td")).toHaveLength(2);
  });

  it("only links http(s) URLs", () => {
    const { container } = render(<Markdown text={"[ok](https://example.com) [bad](javascript:alert(1))"} />);
    expect(container.querySelectorAll("a")).toHaveLength(1);
  });
});
