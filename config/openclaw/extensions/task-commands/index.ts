/**
 * Task Commands Plugin for OpenClaw
 *
 * Provides clear_memory tool for resetting workspace .md files from templates.
 * Called via /clear-memory skill.
 */

import * as fs from "fs/promises";
import * as path from "path";

const taskCommandsPlugin = {
  id: "task-commands",
  name: "Task Commands",
  description: "Provides /clear-memory command to reset workspace .md files from templates",
  version: "1.0.0",
  kind: "tool" as const,

  register(api: any) {
    api.registerTool({
      name: "clear_memory",
      description: "用模板重置 workspace 中的所有 .md 文件。直接执行，无需确认。",
      parameters: {
        type: "object",
        properties: {},
        required: [],
      },
      async execute(_id: string, _params: Record<string, never>) {
        try {
          // 获取 workspace 目录
          const workspaceDir = process.env.OPENCLAW_WORKSPACE_DIR || 
            path.join(process.env.OPENCLAW_STATE_DIR || path.join(process.env.HOME || "", ".openclaw"), "workspace");
          
          const templatesDir = path.join(workspaceDir, "markdown_templates");
          
          // 检查模板目录是否存在
          try {
            await fs.access(templatesDir);
          } catch {
            return {
              content: [
                {
                  type: "text",
                  text: `❌ 模板目录不存在: ${templatesDir}\n请确保 markdown_templates 文件夹存在并包含模板文件。`
                }
              ]
            };
          }

          // 如果需要确认，返回确认提示
          if (_params.requireConfirm) {
            const templateFiles = await fs.readdir(templatesDir);
            const mdTemplates = templateFiles.filter((f: string) => f.endsWith(".md"));
            
            return {
              content: [
                {
                  type: "text",
                  text: `⚠️ **确认执行 task-done?**\n\n这将用模板重置以下 .md 文件：\n${mdTemplates.map((f: string) => `  - ${f}`).join("\n")}\n\n💡 提示：会清空当前会话的配置文件\n\n请回复确认，或告诉我 **"确认"** / **"是"** 来执行，或 **"否"** 取消。`
                }
              ]
            };
          }

          // 直接执行重置
          const templateFiles = await fs.readdir(templatesDir);
          const mdTemplates = templateFiles.filter((f: string) => f.endsWith(".md"));
          
          // 读取 workspace 目录中的现有 .md 文件
          const workspaceFiles = await fs.readdir(workspaceDir);
          const existingMdFiles = workspaceFiles.filter((f: string) => f.endsWith(".md"));
          
          const resetFiles: string[] = [];
          const clearedFiles: string[] = [];
          const errors: string[] = [];
          
          // 用模板覆盖对应的文件
          for (const templateFile of mdTemplates) {
            const templatePath = path.join(templatesDir, templateFile);
            const targetPath = path.join(workspaceDir, templateFile);
            
            try {
              const templateContent = await fs.readFile(templatePath, "utf-8");
              await fs.writeFile(targetPath, templateContent, "utf-8");
              resetFiles.push(templateFile);
            } catch (err: any) {
              errors.push(`${templateFile}: ${err.message}`);
            }
          }
          
          // 清空那些没有模板的现有 .md 文件
          for (const existingFile of existingMdFiles) {
            // 跳过已有模板的文件
            if (mdTemplates.includes(existingFile)) continue;
            
            const filePath = path.join(workspaceDir, existingFile);
            try {
              await fs.writeFile(filePath, "", "utf-8");
              clearedFiles.push(existingFile);
            } catch (err: any) {
              errors.push(`${existingFile}: ${err.message}`);
            }
          }

          const timestamp = new Date().toISOString();
          
          let result = `✅ 任务已完成\n`;
          result += `⏰ 时间: ${timestamp}\n\n`;
          
          if (resetFiles.length > 0) {
            result += `🔄 已用模板重置的文件 (${resetFiles.length}):\n`;
            result += resetFiles.map(f => `  - ${f}`).join("\n");
          }
          
          if (clearedFiles.length > 0) {
            result += `\n\n🗑️ 已清空的文件 (无模板, ${clearedFiles.length}):\n`;
            result += clearedFiles.map(f => `  - ${f}`).join("\n");
          }
          
          if (resetFiles.length === 0 && clearedFiles.length === 0) {
            result += `📭 没有找到需要处理的 .md 文件`;
          }
          
          if (errors.length > 0) {
            result += `\n\n⚠️ 处理失败的文件:\n`;
            result += errors.map(e => `  - ${e}`).join("\n");
          }

          return {
            content: [
              {
                type: "text",
                text: result
              }
            ]
          };
        } catch (error: any) {
          return {
            content: [
              {
                type: "text",
                text: `❌ 执行失败: ${error.message}`
              }
            ]
          };
        }
      },
    });
  },
};

export default taskCommandsPlugin;
