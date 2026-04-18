import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

function runPython(script, args) {
  return new Promise((resolve, reject) => {
    const process = spawn("python3", [script, ...args]);

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
        resolve(parsed);
      } catch {
        reject({
          message: "Invalid JSON from Python",
          raw: stdout,
          stderr
        });
      }
    });

    process.on("error", (err) => {
      reject({ message: err.message });
    });
  });
}


export async function runScanner(repoPath, userType = null) {
  try {
    const detectorPath = path.join(__dirname, "analysis/type.py");
    const analyzerPath = path.join(__dirname, "analysis/final_analysis.py");

    // 🔹 Step 1: detect type
    const detected = await runPython(detectorPath, [repoPath]);

    const autoType = detected?.type || "unknown";
    const confidence = detected?.confidence || 0;

    // 🔹 Step 2: decide final type (force override)
    const finalType = userType || autoType;

    // 🔹 Step 3: run analysis
    const analysis = await runPython(analyzerPath, [repoPath, finalType]);

    return {
      repoType: {
        autoType,
        userType: userType || null,
        finalType,
        confidence,
        overridden: Boolean(userType)
      },

      unusedFiles: Array.isArray(analysis.files)
        ? analysis.files.map((f) =>
            typeof f === "string" ? { file: f, confidence: 0.8 } : f
          )
        : [],

      unusedExports: Array.isArray(analysis.unusedExports)
        ? analysis.unusedExports
        : [],

      unusedDeps: Array.isArray(analysis.deps)
        ? analysis.deps.map((d) =>
            typeof d === "string" ? { name: d, confidence: 0.8 } : d
          )
        : [],

      summary: {
        files: analysis.files?.length || 0,
        exports: analysis.unusedExports?.length || 0,
        deps: analysis.deps?.length || 0,
        total:
          (analysis.files?.length || 0) +
          (analysis.unusedExports?.length || 0) +
          (analysis.deps?.length || 0)
      },

      scores: {
        overall: Math.max(
          0,
          100 - ((analysis.files?.length || 0) * 2 + (analysis.deps?.length || 0))
        ),
        reliability: confidence
      },

      error: null
    };

  } catch (error) {
    return {
      repoType: null,
      unusedFiles: [],
      unusedExports: [],
      unusedDeps: [],
      summary: null,
      scores: null,
      error
    };
  }
}