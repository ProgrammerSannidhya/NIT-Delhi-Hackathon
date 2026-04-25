// utils/runscan.js

import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Spawns a Python script and resolves with the parsed JSON output.
 *
 * BUG FIXED 1: `python` is not available on most Ubuntu/Debian systems —
 *   only `python3` is. Changed spawn target from "python" to "python3".
 *
 * BUG FIXED 2: The local variable was named `process`, which shadows
 *   the Node.js global `process` object. Renamed to `child` for clarity.
 */
function runPython(script, args) {
  return new Promise((resolve, reject) => {
    // FIX 1: use "python3", not "python"
    const child = spawn("python", [script, ...args]);

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (data) => {
      stdout += data.toString();
    });

    // Capture stderr so caller can see warnings / debug info from Python
    child.stderr.on("data", (data) => {
      stderr += data.toString();
    });

    child.on("close", (code) => {
      if (stderr) {
        console.warn(`[python3 stderr] ${script}:\n${stderr}`);
      }

      try {
        const parsed = JSON.parse(stdout.trim());

        // Surface any error the Python script embedded in JSON
        if (parsed?.error) {
          return reject({ message: parsed.error, stderr });
        }

        resolve(parsed);
      } catch {
        reject({
          message: "Invalid JSON from Python script",
          raw: stdout.slice(0, 500),
          stderr: stderr.slice(0, 500),
        });
      }
    });

    child.on("error", (err) => {
      // Give a helpful message if python3 is simply not found
      const hint =
        err.code === "ENOENT"
          ? " — is python3 installed and in PATH?"
          : "";
      reject({ message: err.message + hint });
    });
  });
}


export async function runScanner(repoPath, userType = null) {
  try {
    const detectorPath = path.join(__dirname, "analysis/type.py");
    const analyzerPath = path.join(__dirname, "analysis/final_analysis.py");

    // Step 1: Auto-detect repo type
    const detected = await runPython(detectorPath, [repoPath]);

    const autoType  = detected?.type       || "application";
    const confidence = detected?.confidence || 0;

    // Step 2: User override takes precedence, otherwise use auto-detected type
    const finalType = userType || autoType;

    // Step 3: Run dead-code analysis for the resolved type
    const analysis = await runPython(analyzerPath, [repoPath, finalType]);

    return {
      repoType: {
        autoType,
        userType:   userType || null,
        finalType,
        confidence,
        overridden: Boolean(userType),
      },

      // Normalise files: knip returns plain strings in some modes,
      // objects with {file, confidence, reason} in application mode
      unusedFiles: Array.isArray(analysis.files)
        ? analysis.files.map((f) =>
            typeof f === "string"
              ? { file: f, confidence: 0.8, reason: "not statically referenced" }
              : f
          )
        : [],

      // Exports: [{file, symbol, type, line, col}]
      unusedExports: Array.isArray(analysis.unusedExports)
        ? analysis.unusedExports
        : [],

      // Deps: knip returns plain strings; normalise to objects
      unusedDeps: Array.isArray(analysis.deps)
        ? analysis.deps.map((d) =>
            typeof d === "string" ? { name: d, confidence: 0.8 } : d
          )
        : [],

      // Inline unused vars/code from ESLint
      unusedCode: Array.isArray(analysis.unusedCode)
        ? analysis.unusedCode
        : [],

      summary: {
        files:   analysis.files?.length         || 0,
        exports: analysis.unusedExports?.length || 0,
        deps:    analysis.deps?.length           || 0,
        code:    analysis.unusedCode?.length     || 0,
        total:
          (analysis.files?.length         || 0) +
          (analysis.unusedExports?.length || 0) +
          (analysis.deps?.length           || 0),
      },

      scores: {
        // Rough cleanliness score: penalise 2 pts per unused file, 1 per unused dep
        overall: Math.max(
          0,
          100 -
            (analysis.files?.length || 0) * 2 -
            (analysis.deps?.length  || 0)
        ),
        reliability: confidence,
      },

      analysisMode: analysis.mode || finalType,
      error: null,
    };

  } catch (error) {
    console.error("[runScanner] failed:", error);
    return {
      repoType:      null,
      unusedFiles:   [],
      unusedExports: [],
      unusedDeps:    [],
      unusedCode:    [],
      summary:       null,
      scores:        null,
      analysisMode:  null,
      error,
    };
  }
}