# Special GitHub Pages Rod Impact Version Design

## Context

The project is a local LS-PrePost / LS-DYNA keyword generation tool. The full workflow depends on local Python code, local file writes, MCP server startup, and a user-provided LS-PrePost executable path.

GitHub Pages can only host static files. It cannot run the Python backend, start an MCP server, write to a local workspace, or launch LS-PrePost on the user's machine. The special version must therefore separate static demonstration from full local execution.

## Goal

Create a special GitHub Pages-ready version that:

- Hosts a static front page on GitHub Pages.
- Demonstrates one supported scene: `rod_impact_plate`.
- Clearly tells users that full generation and LS-PrePost integration require downloading the local package.
- Provides a direct download link to the complete local special package.
- Keeps all special-version artifacts inside one dedicated folder.

## Selected Approach

Use GitHub Pages as a static demonstration and distribution page.

The Pages site will show the `rod_impact_plate` scenario with a concise engineering explanation, representative parameters, workflow steps, and a download call to action. The complete frontend and Python backend stay inside a downloadable local package. Users run that package on Windows with `start_web_app.cmd` to get the same functionality as the current local project.

## Folder Layout

Create a dedicated folder:

```text
special_pages_rod_impact/
  README.zh-CN.md
  site/
    index.html
    styles.css
  downloads/
    lsprepost-mcp-special-rod-impact.zip
```

`site/` is the folder intended for GitHub Pages publishing.

`downloads/` stores the complete local package zip that users download when they want model generation, backend execution, or LS-PrePost integration.

`README.zh-CN.md` documents the publishing and user flow.

## Static Page Content

The page will use Chinese copy and focus on the selected scene:

- Title: LS-PrePost 圆柱杆冲击钢板演示
- Scene id: `rod_impact_plate`
- Static explanation of what the page can show.
- Representative parameter summary:
  - Solid cylindrical rod.
  - Initial impact velocity.
  - Fixed steel plate target.
  - Controlled material, contact, constraint, and preview workflow.
- A visual schematic built with HTML/CSS so it works on GitHub Pages without runtime dependencies.
- A clear boundary statement:
  - The web page is static.
  - Python backend, MCP tools, keyword generation, workspace writes, and LS-PrePost launch run only after downloading the local package.
- Download button linking to `downloads/lsprepost-mcp-special-rod-impact.zip`.
- Short local usage steps:
  - Download.
  - Extract.
  - Run `start_web_app.cmd`.
  - Set the local `lsprepost*.exe` path when prompted.

## Data Flow

GitHub Pages flow:

```text
User opens Pages URL
  -> Browser loads static HTML/CSS
  -> User reads the rod impact plate demo
  -> User downloads the local package if more functionality is needed
```

Local package flow:

```text
User extracts zip
  -> Runs start_web_app.cmd
  -> Local Python server starts
  -> Browser opens local web app
  -> User generates and validates models locally
  -> LS-PrePost is launched only on the user's own machine
```

## Error Handling and User Guidance

The static page will avoid implying that GitHub Pages can run backend features.

The README and page copy will explicitly state that:

- GitHub Pages cannot run Python.
- GitHub Pages cannot launch LS-PrePost.
- The download package is required for full functionality.
- Each machine must configure its own LS-PrePost executable path.

If the zip is missing, the link will visibly fail during local verification before delivery.

## Testing

Verification will include:

- Open `special_pages_rod_impact/site/index.html` locally and check that the page renders without a dev server.
- Confirm the download link points to an existing file under `special_pages_rod_impact/downloads/`.
- Confirm the page and README do not claim that backend features run directly on GitHub Pages.
- Optionally run the existing packaging script if a fresh local package is needed.

## Out of Scope

- Running Python backend code on GitHub Pages.
- Connecting a GitHub Pages-hosted frontend to a local backend.
- Deploying a remote backend service.
- Implementing new LS-DYNA model generation capabilities.
