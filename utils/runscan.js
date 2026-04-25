import { spawn } from "child_process";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Spawns a Python script and resolves with parsed JSON output.
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

    child.on("close", () => {
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

      reject({
        message: err.message + hint,
      });
    });
  });
}

export async function runScanner(repoPath, userType = null) {
  try {
    const absolutePath = path.resolve(repoPath);

    const detectorPath = path.join(__dirname, "analysis/type.py");
    const analyzerPath = path.join(__dirname, "analysis/final_analysis.py");

    // Step 1: Detect repository type
    const detected = await runPython(detectorPath, [absolutePath]);

    const autoType = detected?.type || "application";
    const confidence = detected?.confidence || 0;
    const confidenceTier = detected?.confidence_tier || "uncertain";

    // Step 2: Smart override logic
    const HIGH_CONFIDENCE_THRESHOLD = 0.7;

    let finalType;
    let overridden = false;
    let overrideIgnored = false;

    if (!userType || userType === autoType) {
      finalType = autoType;
    } else if (confidence >= HIGH_CONFIDENCE_THRESHOLD) {
      finalType = autoType;
      overrideIgnored = true;

      console.warn(
        `[runScanner] userType="${userType}" ignored — auto-detection is ${confidenceTier} confidence (${confidence}) for "${autoType}"`
      );
    } else {
      finalType = userType;
      overridden = true;
    }

    // Step 3: Run analysis
    const analysis = await runPython(analyzerPath, [
      absolutePath,
      finalType,
    ]);

    // Step 4: Compute overall cleanliness score
    const penaltyScale = Math.max(0.5, confidence);
    const filePenalty = (analysis.files?.length || 0) * 2;
    const depPenalty = (analysis.deps?.length || 0) * 1;
    const exportPenalty = (analysis.unusedExports?.length || 0) * 0.5;

    const overall = Math.round(
      Math.max(
        0,
        100 - (filePenalty + depPenalty + exportPenalty) * penaltyScale
      )
    );

    return {
      repoType: {
        autoType,
        userType: userType || null,
        finalType,
        confidence,
        confidenceTier,
        overridden,
        overrideIgnored,
      },

      unusedFiles: Array.isArray(analysis.files)
        ? analysis.files.map((f) =>
            typeof f === "string"
              ? { path: f, confidence: 0.8 }
              : f
          )
        : [],

      unusedExports: analysis.unusedExports || [],

      unusedDeps: Array.isArray(analysis.deps)
        ? analysis.deps.map((d) =>
            typeof d === "string"
              ? { name: d, confidence: 0.8 }
              : d
          )
        : [],

      unusedCode: analysis.unusedCode || [],

      scores: {
        overall,
        reliability: confidence,
        confidenceTier,
      },

      summary: {
        files: analysis.files?.length || 0,
        exports: analysis.unusedExports?.length || 0,
        deps: analysis.deps?.length || 0,
      },

      error: null,
    };
  } catch (error) {
    console.error("[runScanner] failed:", error);

    return {
      error,
    };
  }
}