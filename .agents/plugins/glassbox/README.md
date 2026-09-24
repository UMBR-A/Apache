# GlassBox

A cross-platform plugin package for Claude Code and ChatGPT-compatible plugin hosts. GlassBox connects to SwiftBrowse's local MCP decision server and adds a decision receipt: the selected operation and target, their probabilities, and the strongest alternatives.

A receipt reports the model's ranking. It is not a natural-language rationale, proof of correctness, or permission to execute an action. GlassBox does not click, type, submit, or change a page.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/) available on your PATH
- A machine supported by the PyTorch backend and enough memory for the Laya checkpoint (downloaded on first use)

The MCP launch command installs SwiftBrowse from this repository with its PyTorch extra. It may download several hundred megabytes of model weights on the first decision. For Apple Silicon users who already installed the MLX extra, replace the package spec with `swiftbrowse-agent[mlx]`.

## Claude Code

From the repository root:

```text
/plugin marketplace add UMBR-A/Apache
/plugin install glassbox@swiftbrowse-plugins
```

Open Claude Code's `/mcp` view and confirm the `glassbox` server is connected. Use `/glassbox:inspect <goal>` when a browser observation tool is available. Claude must obtain the current page observation from a browser tool and pass it to `page_decide`; this plugin does not provide a browser driver.

## ChatGPT / Codex-compatible local marketplace

Add the repository marketplace as a local source in a supported desktop plugin host. For Codex CLI:

```bash
codex plugin marketplace add UMBR-A/Apache --sparse .agents/plugins
```

Then install **GlassBox** from the local plugin directory. For ChatGPT Work/desktop, add the repository as a plugin source if the local marketplace picker is available in your build. A public ChatGPT plugin listing requires a deployed HTTPS MCP endpoint and platform review; this repository package is for local use and testing.

## Tools and receipt

- `decide` — typed classification, scoring, and yes/no decisions.
- `page_decide` — choose one operation and, where needed, one observed element.
- `receipt.operation` — chosen operation and top three operation probabilities.
- `receipt.target` — chosen observed target and top three target probabilities.
- `receipt.offered_elements` — size of the observed element table.

The decision model only returns choices from the options SwiftBrowse supplied. Page text remains untrusted data. Keep a human confirmation step for any consequential action.
