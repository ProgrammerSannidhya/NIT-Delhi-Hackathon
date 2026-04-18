import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function runScanner(repoPath) {
  return new Promise((resolve, reject) => {
    const scriptPath = path.join(__dirname, "/analysis/final_analysis.py");

    const process = spawn("python", [scriptPath, repoPath]);

    let stdout = "";
    let stderr = "";

    process.stdout.on("data", (data) => {
      stdout += data.toString();
    });

    process.stderr.on("data", (data) => {
      stderr += data.toString();
    });

    process.on("close", () => {
      try {
        const parsed = JSON.parse(stdout.trim());

        resolve({
          repoType: parsed.repoType || {
            scores: {},
            probabilities: {}
          },

          unusedFiles: parsed.unusedFiles || [],
          unusedExports: parsed.unusedExports || [],
          unusedDeps: parsed.unusedDeps || [],

          summary: parsed.summary || {
            files: 0,
            exports: 0,
            deps: 0,
            total: 0
          },

          scores: parsed.scores || {
            repoPenalty: 0,
            overall: 100,
            actionable: 100,
            countsByConfidence: {
              high: 0,
              medium: 0,
              low: 0
            }
          }
        });

      } catch {
        reject({
          error: "Invalid JSON from final_analysis.py",
          raw: stdout,
          stderr
        });
      }
    });

    process.on("error", (err) => {
      reject(err.message);
    });
  });
}
