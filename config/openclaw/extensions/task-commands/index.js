import * as fs from "node:fs/promises";
import { appendFileSync, mkdirSync } from "node:fs";
import * as path from "node:path";
import { homedir } from "node:os";

function stateDir() {
  return (
    process.env.OPENCLAW_STATE_DIR ||
    (process.env.USERPROFILE ? path.join(process.env.USERPROFILE, ".openclaw") : "") ||
    (process.env.HOME ? path.join(process.env.HOME, ".openclaw") : "") ||
    path.join(homedir(), ".openclaw")
  );
}

function fileLog(message) {
  try {
    const logDir = path.join(stateDir(), "logs");
    mkdirSync(logDir, { recursive: true });
    appendFileSync(
      path.join(logDir, "task-commands.log"),
      `${new Date().toISOString()} ${message}\n`,
      "utf8",
    );
  } catch {
    // Diagnostic logging only.
  }
}

function textResult(text) {
  return {
    content: [
      {
        type: "text",
        text,
      },
    ],
  };
}

async function pathExists(filePath) {
  try {
    await fs.access(filePath);
    return true;
  } catch {
    return false;
  }
}

function resolveWorkspaceDir() {
  return (
    process.env.OPENCLAW_WORKSPACE_DIR ||
    path.join(stateDir(), "workspace")
  );
}

async function clearMemory() {
  const workspaceDir = resolveWorkspaceDir();
  const templatesDir = path.join(workspaceDir, "markdown_templates");

  fileLog(`clear_memory start workspace=${workspaceDir}`);

  if (!(await pathExists(templatesDir))) {
    fileLog(`missing templatesDir=${templatesDir}`);
    return textResult(
      `Template directory does not exist: ${templatesDir}\n` +
      "Create markdown_templates inside the workspace and put .md templates there.",
    );
  }

  const templateFiles = await fs.readdir(templatesDir);
  const mdTemplates = templateFiles.filter((fileName) => fileName.endsWith(".md"));
  const workspaceFiles = await fs.readdir(workspaceDir);
  const existingMdFiles = workspaceFiles.filter((fileName) => fileName.endsWith(".md"));

  const resetFiles = [];
  const clearedFiles = [];
  const errors = [];

  for (const templateFile of mdTemplates) {
    const templatePath = path.join(templatesDir, templateFile);
    const targetPath = path.join(workspaceDir, templateFile);
    try {
      const templateContent = await fs.readFile(templatePath, "utf8");
      await fs.writeFile(targetPath, templateContent, "utf8");
      resetFiles.push(templateFile);
    } catch (err) {
      errors.push(`${templateFile}: ${err?.message ?? String(err)}`);
    }
  }

  for (const existingFile of existingMdFiles) {
    if (mdTemplates.includes(existingFile)) continue;

    const filePath = path.join(workspaceDir, existingFile);
    try {
      await fs.writeFile(filePath, "", "utf8");
      clearedFiles.push(existingFile);
    } catch (err) {
      errors.push(`${existingFile}: ${err?.message ?? String(err)}`);
    }
  }

  let result = `Task completed\nTime: ${new Date().toISOString()}\n\n`;

  if (resetFiles.length > 0) {
    result += `Reset from templates (${resetFiles.length}):\n`;
    result += resetFiles.map((fileName) => `  - ${fileName}`).join("\n");
  }

  if (clearedFiles.length > 0) {
    result += `${resetFiles.length > 0 ? "\n\n" : ""}Cleared files without templates (${clearedFiles.length}):\n`;
    result += clearedFiles.map((fileName) => `  - ${fileName}`).join("\n");
  }

  if (resetFiles.length === 0 && clearedFiles.length === 0) {
    result += "No workspace .md files needed changes.";
  }

  if (errors.length > 0) {
    result += `\n\nErrors:\n`;
    result += errors.map((error) => `  - ${error}`).join("\n");
  }

  fileLog(`clear_memory done reset=${resetFiles.length} cleared=${clearedFiles.length} errors=${errors.length}`);
  return textResult(result);
}

const taskCommandsPlugin = {
  id: "task-commands",
  name: "Task Commands",
  description: "Provides clear_memory tool to reset workspace .md files from templates",
  version: "1.0.0",
  kind: "tool",

  register(api) {
    fileLog("register called");
    api.logger?.info?.("task-commands: register called");
    api.registerTool({
      name: "clear_memory",
      description: "Reset workspace .md files from workspace/markdown_templates and clear .md files without templates.",
      parameters: {
        type: "object",
        additionalProperties: false,
        properties: {},
      },
      async execute() {
        try {
          return await clearMemory();
        } catch (err) {
          fileLog(`clear_memory failed: ${err?.stack ?? err?.message ?? String(err)}`);
          return textResult(`clear_memory failed: ${err?.message ?? String(err)}`);
        }
      },
    });
  },
};

fileLog("module loaded");

export default taskCommandsPlugin;
