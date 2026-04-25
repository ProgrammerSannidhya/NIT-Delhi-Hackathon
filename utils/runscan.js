// utils/runscan.js

import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Spawns a Python script and resolves with the parsed JSON output.
 */
function runPython(script, args) {
  return new Promise((resolve, reject) => {
    const child = spawn("python3", [script, ...args]);

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (data) => {
      stdout += data.toString();
    });

    child.stderr.on("data", (data) => {
      stderr += data.toString();
    });

    child.on("close", (code) => {
      if (stderr) {
        console.warn(`[python3 stderr] ${script}:\n${stderr}`);
      }

      try {
        const parsed = JSON.parse(stdout.trim());

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

    const autoType        = detected?.type            || "application";
    const confidence      = detected?.confidence      || 0;
    const confidenceTier  = detected?.confidence_tier || "uncertain";
    const rawScores       = detected?.rawScores       || {};

    // Step 2: Smart override logic
    //
    // BUG FIXED: The old code did `const finalType = userType || autoType`
    // which ALWAYS ran the user-supplied type, even when auto-detection was
    // high-confidence. This caused lodash (correctly detected as "library")
    // to run analyze_application() when the user had previously selected
    // "application" — giving wrong unused-file counts and wrong analysis mode.
    //
    // New logic:
    //   - If no userType supplied → always use autoType (most common case)
    //   - If userType supplied AND matches autoType → no real override
    //   - If userType supplied AND differs from autoType:
    //       * High confidence auto-detection → trust auto, flag override as ignored
    //       * Low/uncertain auto-detection  → accept user override
    //
    // "High confidence" threshold: >= 0.70 (tier = "high" or strong "medium")

    const HIGH_CONFIDENCE_THRESHOLD = 0.70;

    let finalType;
    let overridden = false;
    let overrideIgnored = false;

    if (!userType || userType === autoType) {
      // No override or redundant override — just use auto
      finalType = autoType;
      overridden = false;
    } else if (confidence >= HIGH_CONFIDENCE_THRESHOLD) {
      // Auto-detection is confident — ignore the user override
      // (prevents lodash being analyzed as "application" just because
      //  the user clicked the wrong radio button)
      finalType = autoType;
      overridden = false;
      overrideIgnored = true;
      console.warn(
        `[runScanner] userType="${userType}" ignored — ` +
        `auto-detection is ${confidenceTier} confidence (${confidence}) for "${autoType}"`
      );
    } else {
      // Auto-detection is uncertain — respect user override
      finalType = userType;
      overridden = true;
    }

    // Step 3: Run dead-code analysis for the resolved type
    const analysis = await runPython(analyzerPath, [repoPath, finalType]);

    // Step 4: Compute overall cleanliness score
    // Penalise: 2pts per unused file, 1pt per unused dep, 0.5pt per unused export
    // Scale down penalty when confidence is low (we're less sure about the results)
    const penaltyScale  = Math.max(0.5, confidence);   // don't fully trust low-conf results
    const filePenalty   = (analysis.files?.length         || 0) * 2;
    const depPenalty    = (analysis.deps?.length           || 0) * 1;
    const exportPenalty = (analysis.unusedExports?.length || 0) * 0.5;
    const overall       = Math.round(
      Math.max(0, 100 - (filePenalty + depPenalty + exportPenalty) * penaltyScale)
    );

    return {
      repoType: {
        autoType,
        userType:       userType || null,
        finalType,
        confidence,
        confidenceTier,
        overridden,
        overrideIgnored,  // true when user tried to override but auto-detection won
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
        overall,
        reliability:    confidence,
        confidenceTier,
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