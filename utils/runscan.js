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


/**
 * Run the full dead-code analysis pipeline for a cloned repository.
 *
 * @param {string}       repoPath  - Absolute path to the cloned repo on disk.
 * @param {string|null}  userType  - Repo type supplied by the caller (optional).
 * @param {boolean}      override  - When true, force userType instead of autoType.
 * @returns {Promise<object>}       Normalised analysis result matching the API schema.
 */
export async function runScanner(repoPath, userType = null, override = false) {
  try {
    const detectorPath = path.join(__dirname, "analysis/type.py");
    const analyzerPath = path.join(__dirname, "analysis/final_analysis.py");

    // Step 1: auto-detect repo type
    const detected = await runPython(detectorPath, [repoPath]);

    const autoType   = detected?.type       || "unknown";
    const confidence = detected?.confidence || 0;

    // Step 2: resolve final type
    // override=true  → caller explicitly forces userType
    // override=false → always use autoType (userType is ignored)
    const finalType  = (override && userType) ? userType : autoType;
    const overridden = Boolean(override && userType);

    // Step 3: run analysis
    const analysis = await runPython(analyzerPath, [repoPath, finalType]);

    // --- unusedFiles -------------------------------------------------------
    // Python always returns [{file, confidence, reason}] objects now.
    // Keep the string fallback for backward-compatibility during transition.
    const unusedFiles = Array.isArray(analysis.files)
      ? analysis.files.map((f) =>
          typeof f === "string"
            ? { file: f, confidence: 0.8, reason: "not reachable from any entry point" }
            : f
        )
      : [];

    // --- unusedExports -----------------------------------------------------
    // Python returns [{file, name}] objects from knip issues parsing.
    const unusedExports = Array.isArray(analysis.unusedExports)
      ? analysis.unusedExports.filter(
          (e) => e && typeof e.file === "string" && typeof e.name === "string"
        )
      : [];

    // --- unusedDeps --------------------------------------------------------
    // depcheck returns plain strings; map to {name, confidence}.
    const unusedDeps = Array.isArray(analysis.deps)
      ? analysis.deps.map((d) =>
          typeof d === "string"
            ? { name: d, confidence: 0.9 }
            : d
        )
      : [];

    // --- summary -----------------------------------------------------------
    const summary = {
      files:   unusedFiles.length,
      exports: unusedExports.length,
      deps:    unusedDeps.length,
      total:   unusedFiles.length + unusedExports.length + unusedDeps.length
    };

    // --- scores ------------------------------------------------------------
    const scores = {
      overall:     Math.max(0, 100 - (unusedFiles.length * 2 + unusedDeps.length)),
      reliability: confidence
    };

    return {
      repoType: {
        autoType,
        userType: userType || null,
        finalType,
        confidence,
        overridden
      },
      unusedFiles,
      unusedExports,
      unusedDeps,
      summary,
      scores,
      error: null
    };

  } catch (error) {
    return {
      repoType:     null,
      unusedFiles:  [],
      unusedExports:[],
      unusedDeps:   [],
      summary:      null,
      scores:       null,
      error
    };
  }
}